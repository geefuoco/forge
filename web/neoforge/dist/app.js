const app = document.querySelector("#app"),
  dialog = document.querySelector("#dialog"),
  modal = document.querySelector("#dialog-content");

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const [cards, precons] = await Promise.all(
  ["cards", "precons"].map((x) =>
    fetch(`data/${x}.json`).then((r) => {
      if (!r.ok) throw Error("Could not load " + x);
      return r.json();
    }),
  ),
).catch((e) => {
  app.textContent = `Could not load the card library. Serve this folder over HTTP and reload. ${e.message}`;
  throw e;
});
const byName = new Map(cards.map((c) => [c.name.toLowerCase(), c]));
const uid = () => crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
let saved;
try {
  saved = JSON.parse(localStorage.getItem("neoforge-library-v1") || "null");
} catch (e) {
  saved = null;
}
const validDecks = Array.isArray(saved?.decks)
  ? saved.decks.filter(
      (d) =>
        d &&
        typeof d.id === "string" &&
        typeof d.name === "string" &&
        Array.isArray(d.entries) &&
        d.entries.every(
          (e) =>
            e &&
            typeof e.name === "string" &&
            Number.isSafeInteger(e.quantity) &&
            e.quantity > 0 &&
            ["main", "commander"].includes(e.section),
        ),
    )
  : [];
const state = {
  decks: validDecks,
  view: "library",
  deckId: null,
  preview: null,
  query: "",
  color: "",
  type: "",
  mv: "",
  resultPage: 0,
  connected: false,
  url: "http://127.0.0.1:8787",
  token: "",
  snapshot: null,
  selection: { matchId: null, promptId: null, ids: [], number: null, allocations: {} },
  composing: false,
  deferredRender: false,
  importText: "",
  busy: false,
  polling: false,
  storageError: "",
  timer: null,
};
const deck = () => state.decks.find((d) => d.id === state.deckId);
function save() {
  try {
    localStorage.setItem(
      "neoforge-library-v1",
      JSON.stringify({ version: 1, decks: state.decks }),
    );
    state.storageError = "";
  } catch (e) {
    state.storageError =
      "Could not save locally. Export your decks to avoid losing changes.";
    toast(state.storageError);
  }
}
function toast(message) {
  document.querySelector(".flash")?.remove();
  let el = document.createElement("div");
  el.className = "flash";
  el.setAttribute("role", "status");
  el.textContent = message;
  document.body.append(el);
  setTimeout(() => el.remove(), 5000);
}
function openModal(html) {
  modal.innerHTML = `<div class="modal">${html}</div>`;
  dialog.showModal();
}
function closeModal() {
  dialog.close();
}
const total = (d) => d.entries.reduce((n, e) => n + Number(e.quantity), 0);
const card = (n) => byName.get(n.toLowerCase());
function createDeck(name, entries = []) {
  const d = {
    id: uid(),
    name: name.trim() || "Untitled deck",
    entries: structuredClone(entries),
  };
  state.decks.push(d);
  state.deckId = d.id;
  save();
  return d;
}
function count(d, n, section) {
  return (
    d.entries.find((e) => e.name === n && e.section === section)?.quantity || 0
  );
}
function change(n, section, delta) {
  let d = deck(),
    e = d.entries.find((e) => e.name === n && e.section === section);
  if (e) {
    e.quantity += delta;
    if (e.quantity <= 0) d.entries = d.entries.filter((x) => x !== e);
  } else if (delta > 0) d.entries.push({ name: n, quantity: delta, section });
  save();
  render();
}
function validation(d) {
  const out = [];
  let commanders = d.entries.filter((e) => e.section === "commander"),
    identity = new Set(
      commanders.flatMap((e) => (card(e.name)?.identity || "").split("")),
    );
  if (total(d) !== 100) out.push(`Deck has ${total(d)} of 100 cards.`);
  if (!commanders.length) out.push("Choose a commander.");
  if (commanders.reduce((n, e) => n + e.quantity, 0) > 2)
    out.push("More than two commanders selected.");
  const quantities = new Map();
  for (const e of d.entries)
    quantities.set(e.name, (quantities.get(e.name) || 0) + e.quantity);
  for (const [name, quantity] of quantities) {
    const c = card(name);
    if (
      c &&
      quantity > 1 &&
      !/\bBasic\b/i.test(c.type) &&
      !/any number of cards named/i.test(c.text)
    ) {
      const exception = c.text.match(/up to (\w+) cards named/i);
      const limits = { seven: 7, nine: 9 };
      if (!exception || quantity > (limits[exception[1].toLowerCase()] || 1))
        out.push(`${name} has ${quantity} copies.`);
    }
  }
  for (const e of d.entries) {
    const c = card(e.name);
    if (!c) {
      out.push(`Unknown card: ${e.name}.`);
      continue;
    }
    if (commanders.length && [...c.identity].some((x) => !identity.has(x)))
      out.push(`${e.name} is outside your commander’s color identity.`);
    if (e.section === "commander" && !c.commander)
      out.push(`${e.name} may not be eligible as commander.`);
  }
  return out;
}
function shell(content) {
  app.innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><div class="mark"><span>N</span></div>NeoForge</div><nav class="nav" aria-label="Main navigation"><div class="navlabel">Your workspace</div><button data-nav="library" class="${state.view === "library" ? "active" : ""}"><span class="icon">▦</span> Library</button><button data-nav="editor" class="${state.view === "editor" ? "active" : ""}"><span class="icon">◇</span> Deck builder</button><button data-nav="play" class="${state.view === "play" ? "active" : ""}"><span class="icon">♟</span> Play</button></nav><div class="sidefoot"><span class="status-dot ${state.connected ? "on" : ""}"></span>${state.connected ? "PC connected" : "PC offline"}<br>Decks are saved in this browser.</div></aside><div class="workspace"><header class="topbar"><span>COMMANDER / ${state.view.toUpperCase()}</span><div class="top-actions"><button class="button ghost small" data-action="help">How it works</button><button class="button small" data-action="connect"><span class="status-dot ${state.connected ? "on" : ""}"></span>${state.connected ? "Connected" : "Connect PC"}</button></div></header><main class="main">${state.storageError ? `<div class="notice">${esc(state.storageError)}</div>` : ""}${content}</main></div></div>`;
}
function library() {
  shell(
    `<div class="title-row"><div><div class="eyebrow">Your collection of ideas</div><h1>Deck library</h1><p>Build something worth bringing to the table.</p></div><div class="toolbar"><button class="button" data-action="import">Import deck</button><button class="button primary" data-action="new">＋ New deck</button></div></div><div class="hero"><div><div class="eyebrow">The command zone awaits</div><h2>Every great game starts here.</h2><p>Explore the card catalogue, make a deck your own, and take it into a real game with Forge on your PC.</p></div><button class="button" data-action="stocks">Explore starter decks →</button></div><div class="panel"><div class="panel-head"><h2>Your decks</h2><span class="subtle">${state.decks.length} ${state.decks.length === 1 ? "deck" : "decks"}</span></div><div class="panel-body">${
      state.decks.length
        ? `<div class="deck-grid">${state.decks
            .map(
              (d) =>
                `<button class="deck-card" data-open="${esc(d.id)}"><span class="eyebrow">Commander deck</span><h3>${esc(d.name)}</h3><p>${esc(d.entries.find((e) => e.section === "commander")?.name || "Choose your commander")}</p><span class="deck-meta"><span class="symbol">${esc(
                  d.entries
                    .filter((e) => e.section === "commander")
                    .map((e) => card(e.name)?.identity || "")
                    .join(" ") || "◇",
                )}</span> &nbsp; · &nbsp; ${total(d)} cards &nbsp; →</span></button>`,
            )
            .join("")}</div>`
        : `<div class="empty">Your library is ready for its first deck.<br>Start from scratch, import a list, or explore a starter deck.</div>`
    }</div></div>`,
  );
}
function editor() {
  let d = deck();
  if (!d) {
    shell(
      `<div class="title-row"><div><div class="eyebrow">Deck builder</div><h1>Make it yours.</h1><p>Choose a deck to begin building.</p></div><button class="button primary" data-action="new">＋ New deck</button></div><div class="panel"><div class="panel-body">${state.decks.map((x) => `<div class="card-row"><button class="card-name" data-open="${esc(x.id)}">${esc(x.name)}</button><span class="subtle">${total(x)} cards</span></div>`).join("") || '<div class="empty">No decks yet. Create one or visit the library for starter decks.</div>'}</div></div>`,
    );
    return;
  }
  let errors = validation(d),
    commands = d.entries.filter((e) => e.section === "commander"),
    main = d.entries.filter((e) => e.section === "main");
  let filtered = cards.filter(
    (c) =>
      (!state.query ||
        `${c.name} ${c.text}`
          .toLowerCase()
          .includes(state.query.toLowerCase())) &&
      (!state.color ||
        (state.color === "C"
          ? !c.identity
          : [...c.identity].every((x) => state.color.includes(x)))) &&
      (!state.type ||
        c.type.toLowerCase().includes(state.type.toLowerCase())) &&
      (!state.mv ||
        (state.mv === "7+" ? c.mv >= 7 : c.mv === Number(state.mv))),
  );
  let showing = filtered.slice(0, (state.resultPage + 1) * 40),
    selected = state.preview || card(commands[0]?.name || "");
  let bins = Array(8).fill(0);
  main.forEach((e) => {
    let c = card(e.name);
    if (c && !/land/i.test(c.type))
      bins[Math.min(7, Math.max(0, c.mv || 0))] += e.quantity;
  });
  let max = Math.max(1, ...bins);
  shell(
    `<div class="title-row"><div><div class="eyebrow">Deck builder / ${total(d)} cards</div><h1>${esc(d.name)}</h1><p>Make changes freely. Your deck saves as you go.</p></div><div class="toolbar"><button class="button" data-action="deck-menu">Deck options</button><button class="button primary" data-action="test-draw">Test draw</button></div></div><div class="grid"><div><div class="panel"><div class="panel-head"><div><h2>Card catalogue</h2><span class="subtle">${cards.length.toLocaleString()} cards to explore</span></div></div><div class="panel-body"><div class="searchbar"><input id="search" type="search" placeholder="Search name or rules text" value="${esc(state.query)}" aria-label="Search card name or rules text"></div><div class="filters"><select id="color" aria-label="Color identity"><option value="">Any color identity</option>${["C", ...Array.from({ length: 31 }, (_, i) => [..."WUBRG"].filter((_, bit) => (i + 1) & (1 << bit)).join(""))].map((x) => `<option ${state.color === x ? "selected" : ""} value="${x}">${x === "C" ? "Colorless" : x === "WUBRG" ? "All colors" : x + " or colorless"}</option>`).join("")}</select><select id="type" aria-label="Card type"><option value="">Any type</option>${["Creature", "Land", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Battle"].map((x) => `<option ${state.type === x ? "selected" : ""}>${x}</option>`).join("")}</select><select id="mv" aria-label="Mana value"><option value="">Any mana value</option>${["0", "1", "2", "3", "4", "5", "6", "7+"].map((x) => `<option ${state.mv === x ? "selected" : ""}>${x}</option>`).join("")}</select></div><div class="subtle">${filtered.length.toLocaleString()} results ${filtered.length > showing.length ? `· showing ${showing.length}` : ""}</div><div class="result-list">${showing.map((c) => `<div class="card-row"><div class="card-info"><button class="card-name" data-preview="${esc(c.name)}">${esc(c.name)}</button><div class="card-type">${esc(c.type)}</div></div><span class="mana">${esc(c.mana)}</span><button class="button small" data-add="${esc(c.name)}" aria-label="Add ${esc(c.name)} to deck">＋</button></div>`).join("") || '<div class="empty">No cards match these filters.</div>'}${filtered.length > showing.length ? '<button class="button" data-action="more">Show more</button>' : ""}</div></div></div></div><aside><div class="panel"><div class="panel-head"><h2>Deck overview</h2><span class="subtle">${total(d)} / 100</span></div><div class="panel-body"><div class="stat-grid"><div class="stat"><b>${total(d)}</b><span>Cards</span></div><div class="stat"><b>${main.filter((e) => /land/i.test(card(e.name)?.type || "")).reduce((n, e) => n + e.quantity, 0)}</b><span>Lands</span></div><div class="stat"><b>${commands.length}</b><span>Commanders</span></div></div><div class="notice ${errors.length ? "" : "good"}">${errors.length ? `${errors.length} draft ${errors.length === 1 ? "check" : "checks"} to review. ${esc(errors.slice(0, 3).join(" "))}${errors.length > 3 ? " …" : ""}` : "Basic draft checks passed."}<br>Forge performs final legality validation.</div><div class="section-label">Commander</div>${entryRows(commands)}<div class="section-label">Main deck</div><div class="deck-list">${entryRows(main)}</div><div class="section-label">Mana curve · nonlands</div><div class="curve">${bins.map((n, i) => `<div class="bar-wrap" title="${n} cards"><div>${n}</div><div class="bar" style="height:${Math.max(2, (n / max) * 48)}px"></div>${i === 7 ? "7+" : i}</div>`).join("")}</div></div></div><div class="panel" style="margin-top:18px"><div class="panel-head"><h2>Card preview</h2></div><div class="panel-body">${selected ? `<div class="preview"><div class="eyebrow">${esc(selected.mana || "No mana cost")}</div><h3>${esc(selected.name)}</h3><p>${esc(selected.text || "No rules text.")}</p><div class="type">${esc(selected.type)} ${esc(selected.pt || selected.loyalty)}</div></div><div class="toolbar" style="margin-top:12px"><button class="button small" data-add="${esc(selected.name)}">Add to deck</button><button class="button small" data-command="${esc(selected.name)}">Set as commander</button></div>` : '<div class="empty">Select a card to see its details.</div>'}</div></div></aside></div>`,
  );
}
function entryRows(entries) {
  return entries.length
    ? entries
        .map(
          (e) =>
            `<div class="card-row"><span class="qty">${e.quantity}×</span><div class="card-info"><button class="card-name" data-preview="${esc(e.name)}">${esc(e.name)}</button></div><button class="button small" data-minus="${esc(e.name)}" data-section="${e.section}" aria-label="Remove one ${esc(e.name)}">−</button><button class="button small" data-plus="${esc(e.name)}" data-section="${e.section}" aria-label="Add one ${esc(e.name)}">＋</button></div>`,
        )
        .join("")
    : '<p class="subtle">None yet.</p>';
}
function play() {
  let s = state.snapshot;
  shell(
    `<div class="title-row"><div><div class="eyebrow">The table</div><h1>Play Commander</h1><p>A real game powered by Forge running on your PC.</p></div>${state.connected && ["playing", "starting"].includes(s?.status) ? '<button class="button danger" data-action="concede">Concede</button>' : ""}</div>${!state.connected ? `<div class="hero"><div><div class="eyebrow">Your engine, your machine</div><h2>Connect to take a seat.</h2><p>Start the NeoForge companion on your PC, then pair this browser to play against Forge's CPU.</p></div><button class="button primary" data-action="connect">Connect PC</button></div>` : ["playing", "starting"].includes(s?.status) ? "" : `<div class="panel"><div class="panel-head"><h2>Start a match</h2><span class="subtle">Connected to Forge</span></div><div class="panel-body"><div class="split"><div class="field"><label for="human-deck">YOUR DECK</label><select id="human-deck">${deckOptions()}</select></div><div class="field"><label for="ai-deck">CPU DECK</label><select id="ai-deck">${deckOptions()}</select></div></div><button class="button primary" data-action="start" ${state.decks.length && !["playing", "starting"].includes(s?.status) ? "" : "disabled"}>Start real game</button> <span class="subtle">Forge validates both decks before play.</span></div></div>`}${s ? matchView(s) : ""}`,
  );
}
function deckOptions() {
  return state.decks
    .map(
      (d) =>
        `<option value="${esc(d.id)}">${esc(d.name)} · ${total(d)} cards</option>`,
    )
    .join("");
}
function matchView(s) {
  return `<div class="panel" style="margin-top:22px"><div class="panel-head"><div><div class="eyebrow">${esc(s.status)} · Turn ${esc(s.turn ?? "—")}</div><h2>${esc(s.phase || "Waiting for game")}</h2></div><span class="subtle">${esc(s.error || "")}</span></div><div class="panel-body">${s.prompt ? promptView(s.prompt) : ""}<div class="split">${(s.players || []).map((p, i) => `<section><div class="game-header"><h2 class="section-title"><button class="card-name" data-player="${esc(p.id)}">${esc(p.name)}</button> ${i === 0 ? "" : '<span class="subtle">CPU</span>'}</h2><div class="life">${esc(p.life)} <small>life</small></div></div><p class="subtle">Hand ${esc(p.handCount)} · Library ${esc(p.libraryCount)}</p>${p.hand ? zone("Hand", p.hand) : ""}${zone("Battlefield", p.battlefield)}${zone("Command", p.command)}${zone("Graveyard", p.graveyard)}${zone("Exile", p.exile)}</section>`).join("")}</div>${zone(
    "Stack",
    (s.stack || []).map((x) => ({ ...x, name: x.label })),
  )}${s.log?.length ? `<div class="section-label">Game log</div><p class="subtle">${s.log.slice(-8).map(esc).join("<br>")}</p>` : ""}</div></div>`;
}
function zone(name, list = []) {
  return `<div class="zone"><h3>${name} · ${list.length}</h3><div class="zone-cards">${list.map((c) => `<button class="game-card" data-card="${esc(c.id)}">${esc(c.name)}<span>${esc([c.mana, c.type, c.pt, c.tapped ? "Tapped" : "", c.counters].filter(Boolean).join(" · "))}</span></button>`).join("") || '<span class="subtle">Empty</span>'}</div></div>`;
}
function promptView(p) {
  if (p.kind === "allocation") return allocationView(p);
  if (p.kind === "input") return inputView(p);
  if (p.kind === "manipulate") return manipulationView(p);
  let choices = p.choices || [],
    buttons = p.buttons || [];
  return `<div class="prompt"><h3>${esc(p.message || "Your action")}</h3>${p.kind === "unsupported" ? "<p>Forge cannot present this choice in the browser yet.</p>" : ""}${["choices", "order"].includes(p.kind) ? `<p class="subtle">${p.kind === "order" ? "Select choices in the requested order." : "Choose " + (p.min ?? 0) + "–" + (p.max ?? choices.length) + "."}</p>${choices.map((c) => `<label class="choice"><input type="checkbox" name="choice" value="${esc(c.id)}" ${state.selection.ids.includes(String(c.id)) ? "checked" : ""}>${esc(c.label)}</label>`).join("")}<p id="choice-order" class="subtle" aria-live="polite">${p.kind === "order" ? "Order: " + state.selection.ids.map((id) => choices.find((c) => String(c.id) === id)?.label || id).join(" → ") : ""}</p><button class="button primary" data-action="submit-choice">Submit selection</button>` : ""}${p.kind === "number" ? `<div class="field"><label for="number-choice">NUMBER (${esc(p.min ?? 0)}–${esc(p.max ?? "")})</label><input id="number-choice" type="number" min="${esc(p.min ?? 0)}" max="${esc(p.max ?? "")}" value="${esc(state.selection.number ?? p.min ?? 0)}"></div><button class="button primary" data-action="submit-number">Submit</button>` : ""}<div class="toolbar">${buttons.map((b) => `<button class="button" data-prompt-button="${esc(b.id)}" ${b.enabled ? "" : "disabled"}>${esc(b.label)}</button>`).join("")}${!buttons.length && ["confirm", "message", "priority"].includes(p.kind) ? '<button class="button" data-prompt-button="ok">OK</button><button class="button" data-prompt-button="cancel">Cancel</button>' : ""}</div></div>`;
}
function inputView(p) {
  const options = p.options;
  return `<form class="prompt" id="input-form" data-prompt-id="${esc(p.id)}" data-match-id="${esc(state.snapshot.matchId)}"><h3>${esc(p.title || "Enter a response")}</h3><div class="field"><label for="prompt-input">${esc(p.message)}</label>${options == null
    ? `<input id="prompt-input" data-prompt-control="input" data-prompt-id="${esc(p.id)}" type="text" ${p.numeric ? 'inputmode="numeric"' : ""} value="${esc(state.selection.inputValue)}">`
    : `<select id="prompt-input" data-prompt-control="input" data-prompt-id="${esc(p.id)}" ${options.length ? "" : "disabled"}>${options.map((option) => `<option value="${esc(option.id)}" ${state.selection.optionId === option.id ? "selected" : ""}>${esc(option.label)}</option>`).join("")}</select>`}</div>${options?.length === 0 ? '<p class="subtle">No options are available. Cancel to return to the game.</p>' : ""}<div class="toolbar"><button class="button primary" type="submit" ${options?.length === 0 ? "disabled" : ""}>Confirm response</button><button class="button" type="button" data-action="cancel-input">Cancel</button></div></form>`;
}
function manipulationCards(p) {
  const cards = new Map(p.cards.map((card) => [card.id, card]));
  return state.selection.cardIds.map((id) => cards.get(id));
}
function manipulationDestinations(p, ordered, sourceId) {
  const remaining = ordered.filter((card) => card.id !== sourceId);
  return Array.from({ length: remaining.length + 1 }, (_, index) => index).filter((index) =>
    p.toAnywhere || (p.toTop && remaining.slice(0, index).every((card) => card.movable)) ||
    (p.toBottom && remaining.slice(index).every((card) => card.movable)));
}
function manipulationView(p) {
  const ordered = manipulationCards(p), movable = ordered.filter((card) => card.movable);
  const sourceId = state.selection.sourceId;
  const destinations = sourceId ? manipulationDestinations(p, ordered, sourceId) : [];
  if (!destinations.includes(Number(state.selection.destination))) state.selection.destination = destinations[0] ?? null;
  return `<form class="prompt" id="manipulation-form" data-prompt-id="${esc(p.id)}" data-match-id="${esc(state.snapshot.matchId)}"><h3>${esc(p.message)}</h3><p class="subtle">Move the available cards, then confirm the complete order. The first card is at the top.</p><ol class="manipulation-list">${ordered.map((card) => `<li><span>${esc(card.label)}</span><small>${card.movable ? "Movable" : "Fixed"}</small></li>`).join("")}</ol><div class="manipulation-controls"><div class="field"><label for="manipulation-source">Card to move</label><select id="manipulation-source" data-prompt-control="source" ${movable.length ? "" : "disabled"}>${movable.map((card) => `<option value="${esc(card.id)}" ${sourceId === card.id ? "selected" : ""}>${esc(ordered.indexOf(card) + 1)}. ${esc(card.label)}</option>`).join("")}</select></div><div class="field"><label for="manipulation-destination">New position</label><select id="manipulation-destination" data-prompt-control="destination" ${destinations.length ? "" : "disabled"}>${destinations.map((index) => `<option value="${index}" ${Number(state.selection.destination) === index ? "selected" : ""}>${index + 1}${index === 0 ? " · Top" : index === ordered.length - 1 ? " · Bottom" : ""}</option>`).join("")}</select></div><button class="button" id="manipulation-move" data-prompt-control="move" type="button" data-action="move-manipulation" ${destinations.length ? "" : "disabled"}>Move card</button></div><p id="manipulation-feedback" role="status">${esc(state.selection.moveMessage || "")}</p><div class="toolbar"><button class="button primary" type="submit">Confirm order</button><button class="button" type="button" data-action="reset-manipulation">Reset order</button></div></form>`;
}
function allocationAmounts(p) {
  return p.targets.map((target) => ({
    id: target.id,
    amount: state.selection.allocations[target.id] === ""
      ? NaN
      : Number(state.selection.allocations[target.id] ?? target.min),
  }));
}
function allocationIssue(p, amounts) {
  let assigned = 0, earlierBelowLethal = false;
  for (let i = 0; i < p.targets.length; i++) {
    const target = p.targets[i], amount = amounts[i].amount;
    if (!Number.isSafeInteger(amount) || amount < target.min || amount > target.max)
      return `Enter a whole number from ${target.min} to ${target.max} for ${target.label}.`;
    if (p.allocationKind === "combat" && !p.divideFreely && earlierBelowLethal && amount > 0 && (p.ordered || target.defender))
      return target.defender
        ? "Assign lethal damage to every blocker before the defender."
        : "Assign lethal damage to earlier blockers first.";
    if (!target.defender) earlierBelowLethal ||= amount < target.lethal;
    assigned += amount;
  }
  return assigned === p.total ? "" : `Assign exactly ${p.total} ${p.amountLabel}.`;
}
function allocationView(p) {
  const amounts = allocationAmounts(p), issue = allocationIssue(p, amounts);
  const assigned = amounts.reduce((sum, entry) => sum + entry.amount, 0);
  const remaining = Number.isSafeInteger(assigned) ? p.total - assigned : "?";
  return `<form class="prompt" id="allocation-form"><h3>${esc(p.message)}</h3><p>Allocate ${esc(p.total)} ${esc(p.amountLabel)} and confirm your assignment.</p>${p.allocationKind === "combat" && !p.divideFreely ? `<p class="subtle">${p.ordered ? "Earlier blockers need lethal damage before later targets." : "You may divide damage among blockers in any order."} Damage to the defender requires lethal damage on every blocker.</p>` : ""}<div class="allocation-targets">${p.targets.map((target, index) => `<div class="allocation-target"><label for="allocation-${index}">${esc(target.label)}${p.allocationKind === "combat" && !target.defender ? `<small>Lethal damage ${esc(target.lethal)}</small>` : ""}${target.defender ? "<small>Defender</small>" : ""}</label><input id="allocation-${index}" name="allocation" data-allocation="${esc(target.id)}" type="number" inputmode="numeric" step="1" min="${esc(target.min)}" max="${esc(target.max)}" value="${esc(state.selection.allocations[target.id] ?? target.min)}" required aria-describedby="allocation-error"></div>`).join("")}</div><p id="allocation-remaining" role="status">${esc(remaining)} remaining of ${esc(p.total)}</p><p id="allocation-error" class="subtle" aria-live="polite">${esc(issue)}</p><div class="toolbar"><button class="button primary" type="submit" ${issue ? "disabled" : ""}>Confirm assignment</button><button class="button" type="button" data-action="reset-allocation">Reset</button>${p.maySkip ? '<button class="button" type="button" data-action="skip-allocation">Assign another creature first</button>' : ""}</div></form>`;
}
function updateAllocationFeedback() {
  const p = state.snapshot?.prompt;
  if (p?.kind !== "allocation") return;
  const amounts = allocationAmounts(p), issue = allocationIssue(p, amounts);
  const assigned = amounts.reduce((sum, entry) => sum + entry.amount, 0);
  document.querySelector("#allocation-remaining").textContent =
    `${Number.isSafeInteger(assigned) ? p.total - assigned : "?"} remaining of ${p.total}`;
  document.querySelector("#allocation-error").textContent = issue;
  document.querySelector('#allocation-form button[type="submit"]').disabled = !!issue;
}
function render() {
  const active = document.activeElement;
  const editor = active?.closest("form.prompt");
  const ownsEditor = editor?.dataset.promptId === state.snapshot?.prompt?.id && editor?.dataset.matchId === state.snapshot?.matchId;
  if (state.composing && ownsEditor && state.view === "play") {
    state.deferredRender = true;
    return;
  }
  state.composing = false;
  state.deferredRender = false;
  const focusedAllocation = active?.dataset.allocation;
  const focusedControl = ownsEditor ? active?.dataset.promptControl : null;
  const selection = active?.tagName === "INPUT" && active.type === "text"
    ? [active.selectionStart, active.selectionEnd, active.selectionDirection] : null;
  if (state.view === "library") library();
  else if (state.view === "editor") editor();
  else play();
  if (focusedAllocation)
    [...app.querySelectorAll("[data-allocation]")]
      .find((input) => input.dataset.allocation === focusedAllocation)?.focus();
  if (focusedControl) {
    const next = [...app.querySelectorAll("[data-prompt-control]")]
      .find((control) => control.dataset.promptControl === focusedControl);
    next?.focus({ preventScroll: true });
    if (selection && next?.tagName === "INPUT" && next.type === "text") next.setSelectionRange(...selection);
  }
}
async function api(path, options = {}) {
  const r = await fetch(state.url.replace(/\/$/, "") + "/api/v1/" + path, {
    ...options,
    signal: AbortSignal.timeout(15000),
    headers: {
      Authorization: `Bearer ${state.token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  let data;
  try {
    data = await r.json();
  } catch {
    data = {};
  }
  if (!r.ok)
    throw Error(
      data.error?.message || data.error || `PC returned HTTP ${r.status}`,
    );
  if (data.schemaVersion !== 1)
    throw Error("This companion uses an unsupported protocol version.");
  return data;
}
function acceptSnapshot(snapshot) {
  if (
    state.snapshot &&
    snapshot.matchId === state.snapshot.matchId &&
    snapshot.revision < state.snapshot.revision
  )
    return;
  if (
    !Array.isArray(snapshot.players) ||
    !Number.isSafeInteger(snapshot.revision)
  )
    throw Error("The companion returned an invalid match snapshot.");
  if (state.selection.matchId !== snapshot.matchId || state.selection.promptId !== snapshot.prompt?.id) {
    const p = snapshot.prompt;
    state.selection = {
      matchId: snapshot.matchId,
      promptId: snapshot.prompt?.id ?? null,
      ids: [],
      number: null,
      allocations: {},
      inputValue: p?.initial ?? "",
      optionId: p?.options?.find((option) => option.label === p.initial)?.id ?? p?.options?.[0]?.id ?? null,
      cardIds: p?.cards?.map((card) => card.id) ?? [],
      sourceId: p?.cards?.find((card) => card.movable)?.id ?? null,
      destination: null,
      moveMessage: "",
    };
  }
  state.snapshot = snapshot;
}
async function poll() {
  if (!state.connected || state.busy || state.polling) return;
  state.polling = true;
  try {
    let s = await api("match");
    if (
      s?.schemaVersion === 1 &&
      (!state.snapshot ||
        s.revision !== state.snapshot.revision ||
        s.matchId !== state.snapshot.matchId)
    ) {
      acceptSnapshot(s);
      if (state.view === "play") render();
    }
  } catch (e) {
    state.connected = false;
    clearInterval(state.timer);
    toast(`Connection lost: ${e.message}. Reconnect to continue.`);
    render();
  } finally {
    state.polling = false;
  }
}
async function action(kind, extra = {}) {
  if (!state.snapshot?.matchId || state.busy) return;
  const s = state.snapshot;
  const ownsPrompt = () => state.snapshot?.matchId === s.matchId && state.snapshot?.prompt?.id === s.prompt?.id;
  state.busy = true;
  try {
    let result = await api("action", {
      method: "POST",
      body: JSON.stringify({
        matchId: s.matchId,
        revision: s.revision,
        promptId: s.prompt?.id,
        kind,
        ...extra,
      }),
    });
    if (!ownsPrompt()) return;
    if (result?.players) acceptSnapshot(result);
    else {
      let next = await api("match");
      if (!ownsPrompt()) return;
      acceptSnapshot(next);
    }
    render();
  } catch (e) {
    if (!ownsPrompt()) return;
    if (/stale (revision|prompt)/i.test(e.message)) {
      try {
        const next = await api("match");
        if (!ownsPrompt()) return;
        acceptSnapshot(next);
        render();
      } catch {}
      toast("The game moved on. Review the current prompt and try again.");
    } else toast(`Action failed: ${e.message}`);
  } finally {
    state.busy = false;
  }
}
function importModal() {
  openModal(
    `<h2>Import a deck</h2><p>Paste a quantity list or choose a .dck or text file. Use a [Commander] section or a “Commander” heading to identify commanders.</p><div class="field"><label for="import-file">CHOOSE FILE</label><input id="import-file" type="file" accept=".dck,.txt,text/plain"></div><div class="field"><label for="import-text">DECK LIST</label><textarea id="import-text" placeholder="[Commander]\n1 Hearthhull, the Worldseed\n[Main]\n1 Forest">${esc(state.importText)}</textarea></div><div class="modal-actions"><button class="button" data-action="close">Cancel</button><button class="button primary" data-action="parse-import">Review import</button></div>`,
  );
}
function parseImport(text) {
  let section = "main",
    name = "Imported deck",
    entries = [],
    unknown = [],
    unparsed = [];
  for (let raw of text.split(/\r?\n/)) {
    let line = raw.trim();
    if (!line || line.startsWith("//") || line.startsWith("#")) continue;
    if (/^\[metadata\]/i.test(line) || /^\[general\]/i.test(line)) {
      section = "metadata";
      continue;
    }
    if (/^name\s*=/i.test(line)) {
      name = line.replace(/^name\s*=\s*/i, "");
      continue;
    }
    if (/^\[?commander\]?\s*:?$/i.test(line)) {
      section = "commander";
      continue;
    }
    if (/^\[?(main|mainboard|deck)\]?\s*:?$/i.test(line)) {
      section = "main";
      continue;
    }
    if (/^\[/.test(line)) {
      section = "skip";
      continue;
    }
    if (section === "skip" || section === "metadata") continue;
    line = line.replace(/\|.*$/, "");
    let m = line.match(/^(?:(\d+)\s*x?\s+)?(.+?)(?:\s+\([^)]*\)\s*\d*)?$/i);
    if (!m) {
      unparsed.push(line);
      continue;
    }
    let c = card(m[2]);
    if (!c) {
      unknown.push(line);
      continue;
    }
    let q = Number(m[1] || 1);
    if (!Number.isSafeInteger(q) || q < 1) {
      unparsed.push(line);
      continue;
    }
    let e = entries.find((e) => e.name === c.name && e.section === section);
    if (e) e.quantity += q;
    else entries.push({ name: c.name, quantity: q, section });
  }
  return { name, entries, unknown, unparsed };
}
function exportDeck(d) {
  let text =
    `[metadata]\nName=${d.name}\n\n[Commander]\n` +
    d.entries
      .filter((e) => e.section === "commander")
      .map((e) => `${e.quantity} ${e.name}`)
      .join("\n") +
    `\n\n[Main]\n` +
    d.entries
      .filter((e) => e.section === "main")
      .map((e) => `${e.quantity} ${e.name}`)
      .join("\n") +
    "\n";
  let a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  a.download = (d.name.replace(/[^a-z0-9_-]+/gi, "-") || "deck") + ".dck";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
let importDraft;
app.addEventListener("click", async (e) => {
  let b = e.target.closest("button");
  if (!b) return;
  let ds = b.dataset;
  if (ds.nav) {
    state.view = ds.nav;
    render();
    return;
  }
  if (ds.open) {
    state.deckId = ds.open;
    state.view = "editor";
    state.preview = null;
    render();
    return;
  }
  if (ds.preview) {
    state.preview = card(ds.preview);
    render();
    return;
  }
  if (ds.add) {
    change(ds.add, "main", 1);
    return;
  }
  if (ds.minus) {
    change(ds.minus, ds.section, -1);
    return;
  }
  if (ds.plus) {
    change(ds.plus, ds.section, 1);
    return;
  }
  if (ds.command) {
    const d = deck();
    if (
      d.entries.some((e) => e.section === "commander" && e.name === ds.command)
    )
      return;
    for (const e of d.entries)
      if (e.section === "commander") e.section = "main";
    const existing = d.entries.find(
      (e) => e.name === ds.command && e.section === "main",
    );
    if (existing) {
      existing.quantity--;
      if (!existing.quantity)
        d.entries = d.entries.filter((e) => e !== existing);
    }
    const merged = new Map();
    for (const entry of d.entries) {
      const previous = merged.get(entry.name);
      if (previous) previous.quantity += entry.quantity;
      else merged.set(entry.name, entry);
    }
    d.entries = [...merged.values()];
    d.entries.push({ name: ds.command, quantity: 1, section: "commander" });
    save();
    render();
    return;
  }
  if (ds.card) {
    action("card", { cardId: ds.card });
    return;
  }
  if (ds.player) {
    action("player", { playerId: ds.player });
    return;
  }
  if (ds.promptButton) {
    let id = ds.promptButton.toLowerCase();
    action(id.includes("cancel") ? "cancel" : "ok");
    return;
  }
  let a = ds.action;
  if (a === "new") {
    openModal(
      '<h2>New deck</h2><div class="field"><label for="deck-name">DECK NAME</label><input id="deck-name" placeholder="Untitled deck" maxlength="100"></div><div class="modal-actions"><button class="button" data-action="close">Cancel</button><button class="button primary" data-action="create">Create deck</button></div>',
    );
  }
  if (a === "import") {
    state.importText = "";
    importModal();
  }
  if (a === "stocks") {
    openModal(
      `<h2>Starter decks</h2><p>Begin with a complete deck, then make it your own.</p>${precons.map((p) => `<div class="card-row"><div class="card-info"><strong>${esc(p.name)}</strong><div class="card-type">${esc(p.subtitle)} · ${esc(p.colors)} · ${total(p)} cards</div></div><button class="button" data-stock="${esc(p.id)}">Add to library</button></div>`).join("")}<div class="modal-actions"><button class="button" data-action="close">Done</button></div>`,
    );
  }
  if (a === "deck-menu") {
    openModal(
      `<h2>Deck options</h2><p>${esc(deck().name)} · ${total(deck())} cards</p><div class="toolbar"><button class="button" data-action="rename">Rename</button><button class="button" data-action="duplicate">Duplicate</button><button class="button" data-action="export">Export .dck</button><button class="button danger" data-action="delete">Delete</button></div><div class="modal-actions"><button class="button" data-action="close">Done</button></div>`,
    );
  }
  if (a === "test-draw") {
    const pool = deck()
      .entries.filter((e) => e.section === "main")
      .map((e) => ({ ...e }));
    const hand = [];
    for (let drawn = 0; drawn < 7; drawn++) {
      const remaining = pool.reduce((sum, e) => sum + e.quantity, 0);
      if (!remaining) break;
      let selected = Math.floor(Math.random() * remaining);
      for (const entry of pool) {
        selected -= entry.quantity;
        if (selected < 0) {
          hand.push(entry.name);
          entry.quantity--;
          break;
        }
      }
    }
    openModal(
      `<h2>Test draw</h2><p>A sample hand from your deck. This is not a game and does not enforce rules.</p>${
        hand.map((n) => `<div class="card-row">${esc(n)}</div>`).join("") ||
        "<p>Your main deck is empty.</p>"
      }<div class="modal-actions"><button class="button" data-action="close">Close</button><button class="button primary" data-action="test-draw">Draw again</button></div>`,
    );
  }
  if (a === "more") {
    state.resultPage++;
    render();
  }
  if (a === "help") {
    openModal(
      `<h2>Welcome to NeoForge</h2><p>Build Commander decks from the full local catalogue. Your library is saved in this browser, so export decks to keep a portable copy. The draft checks are a guide; Forge has the final say on legality.</p><p>To play, run the NeoForge companion on your PC and connect using its address and pairing token. Select both decks and start a game against Forge's CPU. This is an early browser test version. Combat damage and divided amounts use an assignment editor. Some other game decisions are still being implemented. The token stays in memory and is cleared when you reload.</p><p><a class="button" href="downloads/neoforge-companion-source.zip" download>Download companion source</a></p><p>Extract the source into your Forge checkout and follow its README. To allow this Site, launch it with <code>python tools/browser-bridge/launch.py --origin ${esc(location.origin)}</code>. Your browser may ask for local-network access when connecting.</p><p>Test draw is a quick sample hand, separate from real play.</p><div class="modal-actions"><button class="button primary" data-action="close">Got it</button></div>`,
    );
  }
  if (a === "connect") {
    openModal(
      `<h2>Connect your PC</h2><p>Start the NeoForge companion on your PC. Enter its loopback address and pairing token below. Your token is kept only until this page is closed or reloaded.</p><div class="field"><label for="host-url">COMPANION ADDRESS</label><input id="host-url" value="${esc(state.url)}"></div><div class="field"><label for="host-token">PAIRING TOKEN</label><input id="host-token" type="password" autocomplete="off" value="${esc(state.token)}"></div><p id="connect-error" class="subtle" role="status"></p><div class="modal-actions">${state.connected ? '<button class="button danger" data-action="disconnect">Disconnect</button>' : ""}<button class="button" data-action="close">Cancel</button><button class="button primary" data-action="pair">Connect</button></div>`,
    );
  }
  if (a === "start") {
    let human = state.decks.find(
        (x) => x.id === document.querySelector("#human-deck").value,
      ),
      ai = state.decks.find(
        (x) => x.id === document.querySelector("#ai-deck").value,
      );
    if (state.busy) return;
    state.busy = true;
    try {
      let result = await api("matches", {
        method: "POST",
        body: JSON.stringify({
          humanDeck: { name: human.name, entries: human.entries },
          aiDeck: { name: ai.name, entries: ai.entries },
        }),
      });
      acceptSnapshot(result);
      render();
    } catch (err) {
      toast(`Could not start match: ${err.message}`);
    } finally {
      state.busy = false;
    }
  }
  if (a === "concede") {
    openModal(
      '<h2>Concede this game?</h2><p>This ends your current game against the CPU.</p><div class="modal-actions"><button class="button" data-action="close">Cancel</button><button class="button danger" data-action="confirm-concede">Concede</button></div>',
    );
  }
  if (a === "submit-choice") {
    const prompt = state.snapshot.prompt;
    const ids = state.selection.ids;
    if (
      ids.length < (prompt.min ?? 0) ||
      ids.length > (prompt.max ?? prompt.choices.length)
    ) {
      toast(
        `Select ${prompt.min ?? 0} to ${prompt.max ?? prompt.choices.length} choices.`,
      );
      return;
    }
    action("choice", { choiceIds: ids });
  }
  if (a === "submit-number") {
    const input = document.querySelector("#number-choice");
    if (!input.reportValidity() || !Number.isSafeInteger(Number(input.value)))
      return;
    action("number", { value: Number(input.value) });
  }
  if (a === "reset-allocation") {
    state.selection.allocations = {};
    render();
  }
  if (a === "skip-allocation") action("skip");
  if (a === "cancel-input") action("cancel");
  if (a === "move-manipulation") {
    const p = state.snapshot?.prompt;
    if (p?.kind !== "manipulate") return;
    const ordered = manipulationCards(p), source = state.selection.sourceId;
    const destination = Number(state.selection.destination);
    if (!ordered.find((card) => card.id === source)?.movable ||
        !manipulationDestinations(p, ordered, source).includes(destination)) return;
    const ids = state.selection.cardIds.filter((id) => id !== source);
    ids.splice(destination, 0, source);
    state.selection.cardIds = ids;
    state.selection.moveMessage = `Card moved to position ${destination + 1}.`;
    render();
  }
  if (a === "reset-manipulation") {
    state.selection.cardIds = state.snapshot.prompt.cards.map((card) => card.id);
    state.selection.destination = null;
    state.selection.moveMessage = "Original order restored.";
    render();
  }
});

app.addEventListener("submit", (e) => {
  if (e.target.id === "input-form") {
    e.preventDefault();
    const p = state.snapshot?.prompt;
    if (p?.kind !== "input" || p.options?.length === 0 || state.composing) return;
    action("input", p.options == null ? { value: state.selection.inputValue } : { optionId: state.selection.optionId });
    return;
  }
  if (e.target.id === "manipulation-form") {
    e.preventDefault();
    if (state.snapshot?.prompt?.kind === "manipulate") action("manipulate", { cardIds: state.selection.cardIds });
    return;
  }
  if (e.target.id !== "allocation-form") return;
  e.preventDefault();
  const prompt = state.snapshot?.prompt;
  if (prompt?.kind !== "allocation") return;
  const amounts = allocationAmounts(prompt);
  if (!e.target.reportValidity() || allocationIssue(prompt, amounts)) return;
  action("allocation", { allocations: amounts });
});

app.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && e.target.closest("#input-form") && !e.isComposing) {
    e.preventDefault();
    action("cancel");
  }
});
app.addEventListener("compositionstart", (e) => {
  if (e.target.id === "prompt-input") state.composing = true;
});
app.addEventListener("compositionend", (e) => {
  if (e.target.id !== "prompt-input") return;
  state.selection.inputValue = e.target.value;
  state.composing = false;
  if (state.deferredRender) render();
});

modal.addEventListener("click", async (e) => {
  let b = e.target.closest("button");
  if (!b) return;
  let a = b.dataset.action;
  if (b.dataset.stock) {
    let p = precons.find((x) => x.id === b.dataset.stock);
    createDeck(p.name, p.entries);
    toast(`${p.name} added to your library.`);
    render();
    return;
  }
  if (a === "close") closeModal();
  if (a === "create") {
    createDeck(document.querySelector("#deck-name").value);
    closeModal();
    state.view = "editor";
    render();
  }
  if (a === "test-draw") {
    closeModal();
    document.querySelector('[data-action="test-draw"]').click();
  }
  if (a === "rename") {
    openModal(
      `<h2>Rename deck</h2><div class="field"><label for="deck-name">DECK NAME</label><input id="deck-name" maxlength="100" value="${esc(deck().name)}"></div><div class="modal-actions"><button class="button" data-action="close">Cancel</button><button class="button primary" data-action="save-name">Save</button></div>`,
    );
  }
  if (a === "save-name") {
    deck().name =
      document.querySelector("#deck-name").value.trim() || "Untitled deck";
    save();
    closeModal();
    render();
  }
  if (a === "duplicate") {
    createDeck(deck().name + " copy", deck().entries);
    closeModal();
    render();
    toast("Deck duplicated.");
  }
  if (a === "export") {
    exportDeck(deck());
    closeModal();
  }
  if (a === "delete") {
    openModal(
      `<h2>Delete ${esc(deck().name)}?</h2><p>This removes the deck from this browser. Export it first if you want a copy.</p><div class="modal-actions"><button class="button" data-action="close">Cancel</button><button class="button danger" data-action="confirm-delete">Delete deck</button></div>`,
    );
  }
  if (a === "confirm-delete") {
    state.decks = state.decks.filter((d) => d.id !== state.deckId);
    state.deckId = null;
    save();
    closeModal();
    state.view = "library";
    render();
  }
  if (a === "confirm-concede") {
    closeModal();
    action("concede");
  }
  if (a === "parse-import") {
    state.importText = document.querySelector("#import-text").value;
    importDraft = parseImport(state.importText);
    openModal(
      `<h2>Review import</h2><p>${importDraft.entries.reduce((n, e) => n + e.quantity, 0)} recognized cards. ${importDraft.unknown.length} unknown lines. ${importDraft.unparsed.length} unreadable lines.</p>${importDraft.unknown.length || importDraft.unparsed.length ? `<div class="notice">These lines will be omitted. Review them before importing.<br>${[...importDraft.unknown, ...importDraft.unparsed].map(esc).join("<br>")}</div>` : ""}<div class="field"><label for="import-name">DECK NAME</label><input id="import-name" value="${esc(importDraft.name)}"></div><div class="modal-actions"><button class="button" data-action="back-import">Back</button><button class="button primary" data-action="finish-import" ${importDraft.entries.length ? "" : "disabled"}>Import recognized cards</button></div>`,
    );
  }
  if (a === "back-import") importModal();
  if (a === "finish-import") {
    createDeck(
      document.querySelector("#import-name").value,
      importDraft.entries,
    );
    closeModal();
    state.view = "editor";
    render();
  }
  if (a === "disconnect") {
    state.connected = false;
    state.token = "";
    clearInterval(state.timer);
    closeModal();
    render();
  }
  if (a === "pair") {
    let url = document.querySelector("#host-url").value.trim(),
      token = document.querySelector("#host-token").value.trim(),
      err = document.querySelector("#connect-error");
    try {
      let parsed = new URL(url);
      if (
        !["http:", "https:"].includes(parsed.protocol) ||
        parsed.hostname !== "127.0.0.1" ||
        parsed.username ||
        parsed.password ||
        parsed.pathname !== "/" ||
        parsed.search ||
        parsed.hash
      )
        throw Error(
          "Use http://127.0.0.1:8787 without a path, query, or fragment.",
        );
      if (!token) throw Error("Enter your pairing token.");
      state.url = url;
      state.token = token;
      b.disabled = true;
      let status = await api("status");
      if (status.schemaVersion !== 1 || status.status !== "ready")
        throw Error("The companion is not ready.");
      state.connected = true;
      clearInterval(state.timer);
      state.timer = setInterval(() => {
        if (!document.hidden) poll();
      }, 1000);
      closeModal();
      render();
      poll();
      toast("Connected to Forge on your PC.");
    } catch (error) {
      state.connected = false;
      state.token = "";
      err.textContent = `Could not connect: ${error.message}. Check that the companion is running and allows this site.`;
      b.disabled = false;
    }
  }
});

modal.addEventListener("change", async (e) => {
  if (e.target.id === "import-file" && e.target.files[0])
    document.querySelector("#import-text").value =
      await e.target.files[0].text();
});

app.addEventListener("input", (e) => {
  if (e.target.id === "prompt-input") {
    if (state.snapshot?.prompt?.options == null) state.selection.inputValue = e.target.value;
    else state.selection.optionId = e.target.value;
  }
  if (e.target.name === "allocation") {
    state.selection.allocations[e.target.dataset.allocation] = e.target.value;
    updateAllocationFeedback();
  }
  if (e.target.id === "search") {
    let pos = e.target.selectionStart;
    state.query = e.target.value;
    state.resultPage = 0;
    render();
    let input = document.querySelector("#search");
    input.focus();
    input.setSelectionRange(pos, pos);
  }
});

app.addEventListener("change", (e) => {
  if (e.target.id === "manipulation-source") {
    state.selection.sourceId = e.target.value;
    state.selection.destination = null;
    render();
  }
  if (e.target.id === "manipulation-destination") state.selection.destination = e.target.value;
  if (e.target.name === "choice") {
    const selection = state.selection;
    selection.ids = selection.ids.filter((id) => id !== e.target.value);
    if (e.target.checked) selection.ids.push(e.target.value);
    if (state.snapshot.prompt.kind === "order") {
      document.querySelector("#choice-order").textContent =
        "Order: " +
        selection.ids
          .map(
            (id) =>
              state.snapshot.prompt.choices.find((c) => String(c.id) === id)
                ?.label || id,
          )
          .join(" → ");
    }
  }
  if (e.target.id === "number-choice") state.selection.number = e.target.value;
  if (["color", "type", "mv"].includes(e.target.id)) {
    state[e.target.id] = e.target.value;
    state.resultPage = 0;
    render();
  }
});

render();
