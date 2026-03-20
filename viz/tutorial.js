// ── Tutorial ──────────────────────────────────────────────────────────────────
console.log("tutorial.js loaded");
(function () {

const STEPS = [
  // ── Intro ──
  {
    chapter: "Willkommen",
    title:   "BER-Chronik – Kurzführung",
    text:    "Dieses Tool macht 28 Jahre Planungs- und Baugeschichte des Berliner Flughafens durchsuchbar – mit KI-Antworten, Akteursnetzwerk und interaktiver Timeline. Das Tutorial dauert ca. 2 Minuten.",
    target:  null,
  },
  // ── Kapitel 1: Chat ──
  {
    chapter: "1 · Suche & Chat",
    title:   "Fragen stellen",
    text:    "Das Eingabefeld unterstützt zwei Modi: kurze Begriffe starten eine Volltextsuche, längere Sätze oder Fragen mit \u201E?\u201C gehen an die KI. Wir schicken eine Beispielfrage ab:",
    target:  "#chat-input",
    action:  () => {
      document.getElementById("chat-input").value = "Wann sollte der BER ursprünglich eröffnen?";
      sendChat();
    },
  },
  {
    chapter: "1 · Suche & Chat",
    title:   "KI-Antwort lesen",
    text:    "Die Antwort stützt sich ausschließlich auf Originalabsätze der Chronik. Klickbare Belege wie [p59] springen zur Quelle. Farbig markierte Namen sind Akteure – Klick öffnet ihre Zusammenfassung.",
    target:  "#panel-content",
  },
  // ── Kapitel 2: Netzwerk ──
  {
    chapter: "2 · Akteursnetzwerk",
    title:   "Alle Akteure auf einen Blick",
    text:    "Der Netzwerk-Tab zeigt Personen, Organisationen und Gremien als Graph. Knotengröße = Anzahl Nennungen. Kanten entstehen wenn zwei Akteure im selben Absatz vorkommen.",
    target:  "#tab-network",
    action:  () => {
      switchTab("network");
      if (!networkDrawn) {
        drawNetwork(netNodes, netLinks, entriesByActor);
        networkDrawn = true;
      }
    },
  },
  {
    chapter: "2 · Akteursnetzwerk",
    title:   "Hochtief Konsortium",
    text:    "Als zentraler Auftragnehmer ist das Hochtief-Konsortium stark vernetzt. Wir öffnen den Knoten direkt:",
    target:  "#network-area",
    action:  () => {
      requestAnimationFrame(() => {
        const node = netNodes.find(n => n.id.toLowerCase().includes("hochtief"));
        if (node) selectEntity(node.id);
      });
    },
  },
  {
    chapter: "2 · Akteursnetzwerk",
    title:   "Akteurs-Panel",
    text:    "Das Panel zeigt eine KI-Zusammenfassung und alle Chronik-Absätze dieses Akteurs. Namen im Text sind klickbar und öffnen weitere Zusammenfassungen.",
    target:  "#panel",
  },
  // ── Kapitel 3: Timeline ──
  {
    chapter: "3 · Timeline",
    title:   "Ereignisse in der Zeit",
    text:    "Die Timeline zeigt alle Ereignisse nach Jahr und Typ. Jetzt wechseln wir zurück und markieren alle Einträge mit Hartmut Mehdorn:",
    target:  "#tab-timeline",
    action:  () => {
      switchTab("timeline");
      const anchors = new Set(
        (entriesByActor.get("Hartmut Mehdorn") || []).map(e => e.doc_anchor).filter(Boolean)
      );
      setHighlight("answer", anchors, null, "Hartmut Mehdorn");
    },
  },
  {
    chapter: "3 · Timeline",
    title:   "Hervorgehobene Punkte",
    text:    "Leuchtende Punkte markieren Einträge in denen Mehdorn vorkommt. Klick auf einen Punkt öffnet die Absätze. Timeline und Netzwerk sind synchronisiert – derselbe Akteur wäre in beiden Ansichten markiert.",
    target:  "#chart-area",
  },
  // ── Outro ──
  {
    chapter: "Fertig!",
    title:   "Du kennst die Grundfunktionen",
    text:    "Suche & Chat, Akteursnetzwerk und Timeline \u2013 alles ist miteinander verkn\u00fcpft. \u00dcber den Button \u201ETutorial\u201C oben kannst du diese F\u00fchrung jederzeit neu starten. Viel Erfolg!",
    target:  null,
  },
];

// ── Styles ────────────────────────────────────────────────────────────────────

const _style = document.createElement("style");
_style.textContent = `
#tutorial-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.42);
  z-index: 2000;
  pointer-events: all;
}
#tutorial-bubble {
  display: none;
  position: fixed;
  width: 300px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 28px rgba(0,0,0,0.2);
  padding: 16px 18px 14px;
  z-index: 2001;
  font-size: 0.82rem;
  line-height: 1.55;
  color: #1a1a1a;
}
#tutorial-bubble::before {
  content: "";
  position: absolute;
  width: 0; height: 0;
  border-left: 9px solid transparent;
  border-right: 9px solid transparent;
  left: var(--arrow-left, 50%);
  transform: translateX(-50%);
}
#tutorial-bubble[data-arrow="up"]::before {
  top: -9px;
  border-bottom: 9px solid #fff;
}
#tutorial-bubble[data-arrow="down"]::before {
  bottom: -9px;
  border-top: 9px solid #fff;
}
.tut-chapter {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #888;
  margin-bottom: 4px;
}
.tut-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #111;
  margin-bottom: 7px;
}
.tut-text { margin: 0 0 14px; }
.tut-footer {
  display: flex;
  align-items: center;
  gap: 10px;
}
.tut-next {
  padding: 6px 14px;
  background: #1a1a1a;
  color: #fff;
  border: none;
  border-radius: 5px;
  font-size: 0.8rem;
  cursor: pointer;
  flex-shrink: 0;
}
.tut-next:hover { background: #333; }
.tut-skip {
  background: none; border: none;
  font-size: 0.75rem;
  color: #999;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
}
.tut-skip:hover { color: #555; }
.tut-progress { margin-left: auto; font-size: 0.72rem; color: #bbb; }
#tutorial-btn {
  padding: 3px 10px;
  font-size: 0.75rem;
  background: none;
  border: 1px solid #ccc;
  border-radius: 4px;
  cursor: pointer;
  color: #666;
  margin-left: 12px;
  vertical-align: middle;
}
#tutorial-btn:hover { background: #f0f0f0; color: #111; }
`;
document.head.appendChild(_style);

// ── DOM ───────────────────────────────────────────────────────────────────────

const _overlay = document.createElement("div");
_overlay.id = "tutorial-overlay";
_overlay.style.display = "none";
document.body.appendChild(_overlay);

const _bubble = document.createElement("div");
_bubble.id = "tutorial-bubble";
document.body.appendChild(_bubble);

// ── Positioning ───────────────────────────────────────────────────────────────

function _position(selector) {
  _bubble.style.top = _bubble.style.bottom = _bubble.style.left = _bubble.style.transform = "";
  delete _bubble.dataset.arrow;

  if (!selector) {
    _bubble.style.top       = "50%";
    _bubble.style.left      = "50%";
    _bubble.style.transform = "translate(-50%,-50%)";
    return;
  }

  const el = document.querySelector(selector);
  if (!el) { _position(null); return; }

  const r   = el.getBoundingClientRect();
  const vw  = window.innerWidth;
  const vh  = window.innerHeight;
  const bw  = 300;
  const bh  = _bubble.offsetHeight || 200;
  const gap = 14;
  const pad = 12;

  // Horizontal: center on target, clamp to viewport
  const left = Math.max(pad, Math.min(r.left + r.width / 2 - bw / 2, vw - bw - pad));
  const arrowLeft = Math.max(14, Math.min(r.left + r.width / 2 - left, bw - 14));
  _bubble.style.setProperty("--arrow-left", `${arrowLeft}px`);

  // Vertical: below if space fits, else above, else below clamped
  let top;
  if (r.bottom + gap + bh + pad <= vh) {
    _bubble.dataset.arrow = "up";
    top = r.bottom + gap;
  } else if (r.top - gap - bh - pad >= 0) {
    _bubble.dataset.arrow = "down";
    top = r.top - gap - bh;
  } else {
    _bubble.dataset.arrow = "up";
    top = r.bottom + gap;
  }

  // Clamp both axes so bubble stays fully inside viewport
  top = Math.max(pad, Math.min(top, vh - bh - pad));

  _bubble.style.top  = `${top}px`;
  _bubble.style.left = `${left}px`;
}

// ── Step rendering ────────────────────────────────────────────────────────────

let _step = 0;

function _showStep(idx) {
  const step = STEPS[idx];
  if (!step) { _end(); return; }

  if (step.action) step.action();

  const isLast = idx === STEPS.length - 1;
  _bubble.style.display = "block";
  _bubble.innerHTML = `
    <div class="tut-chapter">${step.chapter}</div>
    <div class="tut-title">${step.title}</div>
    <p class="tut-text">${step.text}</p>
    <div class="tut-footer">
      <button class="tut-next">${isLast ? "Schließen ✓" : "Weiter →"}</button>
      ${!isLast ? `<button class="tut-skip">Überspringen</button>` : ""}
      <span class="tut-progress">${idx + 1} / ${STEPS.length}</span>
    </div>`;

  _bubble.querySelector(".tut-next").onclick = () => _showStep(++_step);
  const skip = _bubble.querySelector(".tut-skip");
  if (skip) skip.onclick = _end;

  _position(step.target);
}

function _end() {
  _overlay.style.display = "none";
  _bubble.style.display  = "none";
  localStorage.setItem("tutorial_seen", "1");
}

// ── Public entry point ────────────────────────────────────────────────────────

function tutorialStart() {
  _step = 0;
  _overlay.style.display = "block";
  _showStep(0);
}

// ── Header button ─────────────────────────────────────────────────────────────

const _btn = document.createElement("button");
_btn.id          = "tutorial-btn";
_btn.textContent = "Tutorial";
document.querySelector("header").appendChild(_btn);
_btn.onclick = tutorialStart;

// ── Auto-start on first visit ─────────────────────────────────────────────────

if (!localStorage.getItem("tutorial_seen")) {
  window.addEventListener("load", () => setTimeout(tutorialStart, 600));
}

})();
