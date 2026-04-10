// ── Chat (in panel) ───────────────────────────────────────────────────────────
// API_URL is defined in config.js (loads first)
// PAGE_PROJECT and DATA_BASE are defined in highlight.js (loads first)

// German stopwords (mirrors api_server.py)
const STOPWORDS = new Set([
  "aber","alle","allem","allen","aller","alles","also","als","am","an","auch",
  "auf","aus","bei","beim","bin","bis","bitte","da","damit","dann","dass","dem",
  "den","denn","der","des","dessen","die","dies","dieser","dieses","doch","dort",
  "durch","ein","eine","einem","einen","einer","eines","er","es","etwa","euch",
  "euer","gibt","haben","hatte","hier","ihm","ihn","ihnen","ihr","ihre","im",
  "immer","ist","kann","kein","keine","mal","man","mehr","mich","mir","mit",
  "nach","nicht","noch","nun","nur","oder","ohne","sehr","sein","sich","sie",
  "sind","soll","sowie","über","um","und","unter","uns","vom","von","vor","war",
  "waren","warum","was","weil","wenn","wer","werden","wie","wird","wir","worden",
  "wurde","wurden","wäre","würde","ziel","zu","zum","zur","zwischen",
]);

function extractKeywords(question) {
  return [...question.matchAll(/[A-Za-zÄÖÜäöüß]+/g)]
    .map(m => m[0].toLowerCase())
    .filter(w => w.length >= 4 && !STOPWORDS.has(w))
    .slice(0, 6);
}

// All loaded entries (filled in boot)
let allEntries = [];

function fulltextSearch(question) {
  const keywords = extractKeywords(question);
  if (!keywords.length) return { hits: [], keywords };
  const hits = allEntries
    .filter(e => keywords.some(kw => (e.text || "").toLowerCase().includes(kw)))
    .sort((a, b) => (a.year || 0) - (b.year || 0) || (a.id || 0) - (b.id || 0));
  return { hits, keywords };
}

function renderChatAnswer(viewEl, question, mode, content) {
  const modeLabel = mode === "ai"
    ? `<span class="chat-mode chat-mode-ai">KI-Antwort</span>`
    : `<span class="chat-mode chat-mode-local">Volltextsuche</span>`;

  if (mode === "ai") {
    const { data } = content;

    // Protect [pXX, YYYY] from marked (it strips unknown reference-style links).
    // Replace them with unique placeholders before parsing, restore after.
    const srcRefMap = new Map();
    let refIdx = 0;
    const protectedAnswer = data.answer.replace(/\[([pP]\d+)(?:,\s*(\d+|\?))?\]/g, (match, anchor, year) => {
      const key = `\x02SRCREF${refIdx++}\x03`;
      const label = year ? `[${anchor}, ${year}]` : `[${anchor}]`;
      srcRefMap.set(key, `<a href="#src-${anchor.toLowerCase()}" class="src-ref">${label}</a>`);
      return key;
    });
    let answerHtml = marked.parse(protectedAnswer);
    for (const [key, html] of srcRefMap) {
      answerHtml = answerHtml.replaceAll(key, html);
    }

    // Source cards with anchor IDs for in-page scrolling
    const sourceEntries = (data.sources || [])
      .map(anchor => entriesByAnchor.get(anchor))
      .filter(Boolean);

    const sourceCards = sourceEntries.map(p =>
      renderParaCard(p, { id: `src-${p.doc_anchor}`, highlightFn: highlightEntities })
    ).join("");

    const sourcesHTML = sourceEntries.length ? `
      <div class="chat-sources-header">Verwendete Quellen (${sourceEntries.length})</div>
      <div class="chat-hits">${sourceCards}</div>` : "";

    viewEl.innerHTML = `
      <div class="chat-meta">${modeLabel}<span class="chat-question-label">${escapeHtml(question)}</span></div>
      <div class="chat-answer-text">${answerHtml}</div>
      ${data.keywords?.length ? `<div class="chat-params">Keywords: ${data.keywords.join(", ")}</div>` : ""}
      ${sourcesHTML}
    `;
    setHighlight("answer", new Set(data.sources || []));
  } else {
    const { hits, keywords } = content;
    const cards = hits.length
      ? hits.map(p => renderParaCard(p, {
          highlightFn: text => highlightWithKeywords(text, keywords),
        })).join("")
      : `<div class="chat-params">Keine Treffer.</div>`;

    viewEl.innerHTML = `
      <div class="chat-meta">${modeLabel}<span class="chat-question-label">${escapeHtml(question)}</span></div>
      ${content.apiError ? `<div class="chat-params" style="color:#c55">API-Fehler: ${escapeHtml(content.apiError)}</div>` : ""}
      ${hits.length ? `<div class="chat-params">${hits.length} Treffer · Keywords: ${keywords.join(", ")}</div>` : ""}
      <div class="chat-hits">${cards}</div>
    `;
    setHighlight("answer", new Set(hits.map(h => h.doc_anchor).filter(Boolean)));
  }
}

async function sendChat() {
  const input    = document.getElementById("chat-input");
  const sendBtn  = document.getElementById("chat-send");
  const question = input.value.trim();
  if (!question) return;

  // Switch to chat view if we're elsewhere (push current view to stack)
  if (currentView.type !== "chat") {
    viewStack.push(currentView);
    currentView = { type: "chat", title: "Suche", renderFn: null, entityKey: null };
    _renderView(currentView);
  }

  const viewEl = document.getElementById("view-chat");
  sendBtn.disabled = true;
  input.disabled   = true;

  if (!isAiMode(question)) {
    // Local keyword search – no API call
    viewEl.innerHTML = `<div class="chat-spinner">Suche …</div>`;
    const result = fulltextSearch(question);
    renderChatAnswer(viewEl, question, "local", result);
    sendBtn.disabled = false;
    input.disabled   = false;
    input.focus();
    return;
  }

  viewEl.innerHTML = `
    <div class="chat-meta">
      <span class="chat-mode chat-mode-ai">KI-Antwort</span>
      <span class="chat-question-label">${escapeHtml(question)}</span>
    </div>
    <div class="chat-answer-text" id="stream-target"></div>`;
  setHighlight("none");  // clear entity focus while answer loads
  let usedFallback = false;
  try {
    const res = await fetch(`${API_URL}/chat/stream`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ question, ...(PAGE_PROJECT && { project_id: PAGE_PROJECT }) }),
      signal:  AbortSignal.timeout(60000),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let rawText = "";
    let buffer  = "";

    outer: while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let parsed;
        try { parsed = JSON.parse(line.slice(6)); } catch { continue; }
        if (typeof parsed === "string") {
          rawText += parsed;
          const target = document.getElementById("stream-target");
          if (target) target.textContent = rawText;
        } else if (parsed.type === "done") {
          renderChatAnswer(viewEl, question, "ai", {
            data: { answer: rawText, sources: parsed.sources, keywords: parsed.keywords },
          });
          break outer;
        } else if (parsed.type === "error") {
          throw new Error(parsed.message);
        }
      }
    }
  } catch (err) {
    console.warn("[chat] API nicht erreichbar, Fallback aktiv:", err?.message ?? err);
    usedFallback = true;
    const result = fulltextSearch(question);
    result.apiError = err?.message ?? String(err);
    renderChatAnswer(viewEl, question, "local", result);
  } finally {
    sendBtn.disabled = false;
    input.disabled   = false;
    if (!usedFallback) input.value = "";
    input.focus();
  }
}

function isAiMode(text) {
  return text.includes("?") || text.trim().split(/\s+/).length > 4;
}

const modeLabel = document.getElementById("input-mode-label");
document.getElementById("chat-input").addEventListener("input", e => {
  const val = e.target.value.trim();
  if (!val) {
    modeLabel.className = "";
    modeLabel.textContent = "";
  } else if (isAiMode(val)) {
    modeLabel.className = "mode-ai";
    modeLabel.textContent = "KI-Frage ✦";
  } else {
    modeLabel.className = "mode-local";
    modeLabel.textContent = "Suche ⌕";
  }
});

document.getElementById("chat-send").addEventListener("click", sendChat);
document.getElementById("chat-input").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

