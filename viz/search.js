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
    const protectedAnswer = data.answer.replace(/\[(?:source:\s*)?\[?([\w][\w\-]*)\]?\]/g, (match, anchor) => {
      const key = `\x02SRCREF${refIdx++}\x03`;
      srcRefMap.set(key, `<a href="#src-${anchor}" class="src-ref">[${anchor}]</a>`);
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

    // Abgebrochen: der Text steht trotzdem da, aber er ist unvollständig, und
    // das muss dranstehen. Ihn wegzuwerfen wäre die schlechtere Auskunft.
    const abbruchHTML = data.abbruch ? `
      <div class="chat-params" style="color:#c55">
        Abgebrochen nach ${data.abbruch.sekunden} s — die Antwort ist unvollständig.
        ${escapeHtml(data.abbruch.grund)}
      </div>` : "";

    viewEl.innerHTML = `
      <div class="chat-meta">${modeLabel}<span class="chat-question-label">${escapeHtml(question)}</span></div>
      ${abbruchHTML}
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

// Dieselben drei Formen, die chat/kern.genannte_quellen() kennt: [anker],
// [[anker]] und [source: anker]. Für einen abgebrochenen Strom gibt es kein
// 'fertig'-Ereignis und damit keine Quellenliste vom Server — hier wird sie
// aus dem Text gewonnen, gegen die vorhandenen Absätze abgeglichen.
function ankerAusText(text) {
  const gesehen = [];
  for (const m of text.matchAll(/\[(?:source:\s*)?\[?([A-Za-z0-9][\w\-]*)\]?\]/g)) {
    if (entriesByAnchor.has(m[1]) && !gesehen.includes(m[1])) gesehen.push(m[1]);
  }
  return gesehen;
}

// Eine unvollständige Antwort — der Text bleibt stehen, mit dem Hinweis, dass
// er es ist. Die Quellenliste kommt sonst aus dem 'fertig'-Ereignis; kam das
// nicht, wird sie aus dem Text selbst gewonnen.
function teilantwort(viewEl, question, text, begonnen, grund) {
  renderChatAnswer(viewEl, question, "ai", {
    data: {
      answer: text,
      sources: ankerAusText(text),
      keywords: [],
      abbruch: { sekunden: Math.round((Date.now() - begonnen) / 1000), grund },
    },
  });
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
  // Außerhalb des try, damit der catch ihn sieht. Stand er drinnen, war
  // schon gelieferter Text beim Abbruch verloren — gemessen 1764 Zeichen auf
  // dem Schirm, danach null.
  let rawText = "";
  const begonnen = Date.now();

  // Eine Frist auf die STILLE, nicht auf die Gesamtdauer. Die alte
  // AbortSignal.timeout(60000) maß etwas anderes als der Vorgang tut: eine
  // Antwort, die stetig Text liefert, ist gesund, gleich wie lange sie
  // braucht. Gemessen gegen ber mit llama3.1:8b: erstes Zeichen nach 26 bis
  // 31 s, fertig nach 57, 81 und 118 s — zwei von drei Fragen liefen in die
  // 60 s. Die Zahl stammte aus der Zeit von llama3.2:3b (19 s / 32 s) und ist
  // beim Modellwechsel stehen geblieben.
  //
  // 150 s liegt über [llm.ollama].stille_sekunden = 120 aus anbieter.toml:
  // gäbe der Browser früher auf als der Server, schnitte er einen Aufruf ab,
  // den der Server für gesund hält — und der Server schriebe weiter in eine
  // geschlossene Verbindung.
  //
  // Hier oben und nicht im try, damit der catch die Zahl nennen kann.
  const STILLE_MS = 150_000;
  const wache = new AbortController();
  let letztes = Date.now();
  let takt = null;

  // Ohne ?project= gibt es kein Projekt, an das die Frage gehen könnte —
  // dann bleibt nur die lokale Volltextsuche.
  if (!PAGE_PROJECT) {
    const result = fulltextSearch(question);
    result.apiError = "Ohne Projekt (?project=…) gibt es keine KI-Antwort.";
    renderChatAnswer(viewEl, question, "local", result);
    sendBtn.disabled = false;
    input.disabled   = false;
    input.focus();
    return;
  }

  try {
    takt = setInterval(() => {
      if (Date.now() - letztes > STILLE_MS) wache.abort(new Error("stille"));
    }, 1000);

    const res = await fetch(
      `${API_URL}/api/projekt/${encodeURIComponent(PAGE_PROJECT)}/chat`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ frage: question }),
        signal:  wache.signal,
      }).finally(() => { letztes = Date.now(); });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.fehler?.meldung || res.statusText);
    }

    // Server-Sent Events mit benannten Ereignissen: die Art steht in der
    // event-Zeile, der Text in der data-Zeile. Der alte Weg schob __done__
    // und __error__ in den Textstrom und klaubte sie hier wieder heraus —
    // ein Absatz, der zufällig so anfing, brachte den Leser durcheinander.
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer  = "";
    let art     = "";
    let abgeschlossen = false;   // kam 'fertig'?

    outer: while (true) {
      const { done, value } = await reader.read();
      letztes = Date.now();      // jedes Bruchstück setzt die Stille zurück
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith("event: ")) { art = line.slice(7).trim(); continue; }
        if (!line.startsWith("data: ")) continue;
        let inhalt;
        try { inhalt = JSON.parse(line.slice(6)); } catch { continue; }
        if (art === "stueck") {
          rawText += inhalt.text;
          const target = document.getElementById("stream-target");
          if (target) target.textContent = rawText;
        } else if (art === "fertig") {
          renderChatAnswer(viewEl, question, "ai", {
            data: { answer: rawText, sources: inhalt.quellen, keywords: inhalt.stichwoerter },
          });
          abgeschlossen = true;
          break outer;
        } else if (art === "abbruch") {
          throw new Error(inhalt.meldung);
        }
      }
    }

    // Ohne 'fertig' hier angekommen heißt: der Strom ist zu Ende, ohne dass er
    // abgeschlossen wurde —
    // der Server ist mitten im Satz weggebrochen. Ohne diesen Zweig blieb der
    // Rohtext im stream-target stehen, ohne Markdown, ohne Quellen, ohne
    // Hinweis; der Knopf wurde wieder frei und nichts sagte, dass etwas fehlt.
    if (!abgeschlossen) {
      if (rawText.trim()) {
        teilantwort(viewEl, question, rawText, begonnen,
                    "Der Strom endete ohne Abschluss.");
      } else {
        throw new Error("Der Strom endete, ohne ein Zeichen zu liefern.");
      }
    }
  } catch (err) {
    console.warn("[chat] Strom abgebrochen:", err?.message ?? err);
    const sekunden = Math.round((Date.now() - begonnen) / 1000);
    const grund = err?.name === "AbortError" || err?.message === "stille"
      ? `Nach ${Math.round(STILLE_MS / 1000)} s ohne ein Zeichen aufgegeben.`
      : `Grund: ${err?.message ?? String(err)}`;

    if (rawText.trim()) {
      teilantwort(viewEl, question, rawText, begonnen, grund);
    } else {
      // Kein Zeichen angekommen: dann ist die Volltextsuche das Beste, was
      // sich noch anbieten lässt.
      usedFallback = true;
      const result = fulltextSearch(question);
      result.apiError = `${grund} (nach ${sekunden} s)`;
      renderChatAnswer(viewEl, question, "local", result);
    }
  } finally {
    // Hier und nicht im inneren Block: läuft schon der fetch auf einen Fehler,
    // liefe das Intervall sonst für immer weiter.
    if (takt !== null) clearInterval(takt);
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

