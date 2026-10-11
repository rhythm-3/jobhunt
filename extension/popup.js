"use strict";
const $ = id => document.getElementById(id);
let data = null;

async function settings() { const s = await chrome.storage.local.get({ base: "http://127.0.0.1:8000", token: "" }); return s; }

async function connect() {
  const s = await settings(); $("base").value = s.base; $("token").value = s.token;
  try {
    const r = await fetch(s.base.replace(/\/$/, "") + "/api/autofill", { headers: s.token ? { Authorization: "Bearer " + s.token } : {} });
    if (r.status === 401) throw new Error("The app needs its dashboard token — add it under “App address”.");
    if (!r.ok) throw new Error("The app answered with an error (" + r.status + ").");
    data = await r.json();
    $("who").textContent = "Filling as " + data.name + ".";
    const sel = $("app");
    for (const a of data.applications) { const o = document.createElement("option"); o.value = a.id; o.textContent = a.company + " — " + a.title; sel.append(o); }
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const page = ((tab && tab.title) || "").toLowerCase() + " " + ((tab && tab.url) || "").toLowerCase();
    const guess = data.applications.find(a => a.company && page.includes(a.company.toLowerCase().split(/\s+/)[0]));
    if (guess) sel.value = guess.id;                 // pre-select the application for the company on this page
    $("fill").disabled = false;
  } catch (e) {
    $("who").textContent = "Not connected."; $("out").className = "err";
    $("out").textContent = /Failed to fetch/i.test(String(e.message)) ? "Can't reach OfferPilot. Start the app on this computer, then open this again." : e.message;
  }
}

$("fill").onclick = async () => {
  const btn = $("fill"); btn.disabled = true; $("out").textContent = "";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const app = data.applications.find(a => a.id === $("app").value);
    await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["fill.js"] });
    const res = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true },
      func: (v, c) => window.__offerpilotFill(v, c), args: [data.values, app ? app.cover_letter : ""] });
    const filled = res.flatMap(r => (r.result && r.result.filled) || []), left = [...new Set(res.flatMap(r => (r.result && r.result.left) || []))];
    $("out").className = filled.length ? "ok" : "";
    $("out").innerHTML = "";
    const p = document.createElement("p"); p.textContent = filled.length ? `Filled ${filled.length} field${filled.length > 1 ? "s" : ""}, outlined in green. Check them before you submit.` : "No empty fields I recognise on this page.";
    $("out").append(p);
    if (left.length) { const q = document.createElement("p"); q.className = "muted"; q.textContent = "Left for you:"; const ul = document.createElement("ul");
      for (const l of left.slice(0, 8)) { const li = document.createElement("li"); li.textContent = l; ul.append(li); } $("out").append(q, ul); }
  } catch (e) { $("out").className = "err"; $("out").textContent = "Couldn't fill this page: " + e.message; }
  btn.disabled = false;
};
for (const id of ["base", "token"]) $(id).onchange = async () => { await chrome.storage.local.set({ [id]: $(id).value.trim() || (id === "base" ? "http://127.0.0.1:8000" : "") }); data = null; $("fill").disabled = true; connect(); };
connect();
