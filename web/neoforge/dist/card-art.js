const records = new Map();
const queue = [];
const limit = 500;
const storageKey = "neoforge-card-art-v1";
let active = 0;
let scheduled = false;
const keyFor = (name) => String(name || "").trim().toLowerCase();
const visibleName = (name) => !!keyFor(name) && !/^(face.down card|unknown card|hidden card)$/i.test(name);
const escape = (text) => String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
function imageURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "cards.scryfall.io" && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
try {
  for (const [name, url] of Object.entries(JSON.parse(localStorage.getItem(storageKey) || "{}"))) {
    if (records.size < limit && imageURL(url)) records.set(name, { status: "ready", url });
  }
} catch {}
function remember() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries([...records].filter(([, record]) => record.status === "ready").map(([name, record]) => [name, record.url]))));
  } catch {}
}
function update(node) {
  const name = node.dataset.artName;
  const record = records.get(keyFor(name));
  const status = !visibleName(name) ? "hidden" : record?.status || "loading";
  if (node.dataset.artState === status && (status !== "ready" || node.querySelector("img")?.src === record.url)) return;
  node.dataset.artState = status;
  node.replaceChildren();
  if (status === "ready") {
    const image = new Image();
    image.alt = "";
    image.referrerPolicy = "no-referrer";
    image.src = record.url;
    image.addEventListener("error", () => {
      records.set(keyFor(name), { status: "unavailable" });
      refresh(name);
      remember();
    }, { once: true });
    node.append(image);
  } else {
    const label = document.createElement("span");
    label.className = "art-placeholder";
    label.textContent = status === "hidden" ? "N" : name;
    node.append(label);
    const note = document.createElement("small");
    note.textContent = status === "hidden" ? "Hidden card" : status === "unavailable" ? "Artwork unavailable" : "Loading artwork";
    node.append(note);
  }
  document.dispatchEvent(new CustomEvent("card-art-status"));
}
function refresh(name) {
  for (const node of document.querySelectorAll("[data-art-name]")) if (keyFor(node.dataset.artName) === keyFor(name)) update(node);
}
function schedule() {
  if (scheduled || !queue.length) return;
  scheduled = true;
  setTimeout(() => {
    scheduled = false;
    if (active < 3) {
      const name = queue.shift();
      if (![...document.querySelectorAll("[data-art-name]")].some((node) => keyFor(node.dataset.artName) === keyFor(name))) {
        records.delete(keyFor(name));
        schedule();
        return;
      }
      active++;
      load(name).finally(() => { active--; schedule(); });
    }
    schedule();
  }, 200);
}
async function load(name) {
  const key = keyFor(name);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch("https://api.scryfall.com/cards/named?exact=" + encodeURIComponent(name), { signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer" });
    if (!response.ok) throw Error("Artwork lookup failed");
    const card = await response.json();
    const face = card.card_faces?.find((candidate) => keyFor(candidate.name) === key) || card.card_faces?.[0];
    const url = imageURL(card.image_uris?.normal || face?.image_uris?.normal);
    if (!url) throw Error("No card image");
    records.set(key, { status: "ready", url });
    remember();
  } catch {
    records.set(key, { status: "unavailable" });
  } finally {
    clearTimeout(timeout);
    refresh(name);
  }
}
function request(name) {
  const key = keyFor(name);
  if (!visibleName(name) || records.has(key)) return;
  if (records.size >= limit) {
    const removable = [...records].find(([, value]) => value.status !== "loading");
    if (removable) records.delete(removable[0]);
    else return;
  }
  records.set(key, { status: "loading" });
  queue.push(name);
  schedule();
}
export function artwork(name, className = "") {
  return `<span class="card-art ${className}" data-art-name="${escape(name || "Face-down card")}"></span>`;
}
export function hydrateArt(root = document) {
  const nodes = [...(root.matches?.("[data-art-name]") ? [root] : []), ...root.querySelectorAll("[data-art-name]")];
  for (const node of nodes) { request(node.dataset.artName); update(node); }
}
export function retryArt() {
  for (const [key, record] of records) if (record.status === "unavailable") records.delete(key);
  hydrateArt();
}
export function artStatus() {
  const nodes = [...document.querySelectorAll(".game-table [data-art-name]")];
  const missing = nodes.filter((node) => node.dataset.artState === "unavailable").length;
  const loading = nodes.some((node) => node.dataset.artState === "loading");
  return missing ? `${missing} card image${missing === 1 ? "" : "s"} unavailable` : loading ? "Loading card artwork…" : "Card images · Scryfall";
}
