"use strict";
// Assistant: a small chat window that answers questions about the app from its built-in guide.
// Depends on app.js / toolkit.js / outreach.js globals: $, $$, esc, api, toast, go, S, I, refreshJobs, outreachForm, interviewForm, offerForm.

const ASK = { open: false, busy: false, log: [], info: null };

function askAction(a) {
  if (a.do) {
    const run = { refresh: () => refreshJobs(), addjob: () => window.open("/clip", "_blank"), interview_add: () => interviewForm(), offer_add: () => offerForm(),
      outreach_add: () => { go("outreach"); setTimeout(() => outreachForm(), 400); } }[a.do];
    if (run) run();
  } else if (a.view) {
    if (a.sub) ({ jobs: () => S.jobsTab = a.sub, settings: () => S.setTab = a.sub, interviews: () => S.ivTab = a.sub, outreach: () => S.otab = a.sub }[a.view] || (() => {}))();
    go(a.view);
  }
  if (innerWidth < 760) askToggle(false);
}

function askDraw() {
  const log = $("#asklog"); if (!log) return;
  const msg = (m, i) => m.role === "user" ? `<div class="askmsg me"><span class="sr">You: </span>${esc(m.text)}</div>`
    : `<div class="askmsg bot"><span class="sr">Assistant: </span>${esc(m.text).replace(/\n/g, "<br>")}
        ${(m.actions || []).length ? `<div class="askacts">${m.actions.map((a, j) => `<button class="btn sm ${j ? "" : "primary"}" data-aa="${i}:${j}">${esc(a.label)}</button>`).join("")}</div>` : ""}
        ${(m.related || []).length ? `<div class="askrel"><span class="small muted">Related:</span>${m.related.map(r => `<button class="chip linkchip" data-ar="${esc(r.id)}" data-art="${esc(r.title)}">${esc(r.title)}</button>`).join("")}</div>` : ""}
        ${m.method && !["guide", "status", "none"].includes(m.method) ? `<div class="small muted asknote">Written by the AI from the app's guide.</div>` : ""}</div>`;
  log.innerHTML = (ASK.log.length ? "" : `<div class="askmsg bot">Hi! I know how every part of ${esc((window.BRAND || {}).name || "OfferPilot")} works. Ask me how to do something, or what to do next.
      <div class="askrel">${((ASK.info || {}).starters || []).map(s => `<button class="chip linkchip" data-as="${esc(s)}">${esc(s)}</button>`).join("")}</div></div>`)
    + ASK.log.map(msg).join("") + (ASK.busy ? `<div class="askmsg bot muted" id="askwait">Thinking… the AI can take up to a minute.</div>` : "");
  $$("[data-aa]", log).forEach(b => b.onclick = () => { const [i, j] = b.dataset.aa.split(":"); askAction(ASK.log[+i].actions[+j]); });
  $$("[data-ar]", log).forEach(b => b.onclick = () => askSend("topic:" + b.dataset.ar, b.dataset.art));
  $$("[data-as]", log).forEach(b => b.onclick = () => askSend(b.dataset.as));
  log.scrollTop = log.scrollHeight;
}

async function askSend(text, shown) {
  text = (text || "").trim(); if (!text || ASK.busy) return;
  const history = ASK.log.slice(-6).map(m => ({ role: m.role, text: m.text }));
  ASK.log.push({ role: "user", text: shown || text }); ASK.busy = true; askDraw();
  const inp = $("#askin"), btn = $("#askgo"); if (btn) btn.disabled = true;
  try {
    const r = await api("/assistant", { method: "POST", body: { message: text, history, product: (window.BRAND || {}).name } });
    ASK.log.push({ role: "assistant", text: r.answer, actions: r.actions, related: r.related, method: r.method });
  } catch (e) { ASK.log.push({ role: "assistant", text: "Sorry, I couldn't answer that just now (" + e.message + ")." }); }
  ASK.busy = false; if (btn) btn.disabled = false; askDraw(); if (inp && ASK.open) inp.focus();
}

function askToggle(on) {
  ASK.open = on == null ? !ASK.open : on;
  const p = $("#askpanel"), f = $("#askfab");
  p.hidden = !ASK.open; f.setAttribute("aria-expanded", String(ASK.open));
  if (ASK.open) { askDraw(); $("#askin").focus(); if (!ASK.info) api("/assistant").then(i => { ASK.info = i; askDraw(); }).catch(() => {}); }
  else f.focus();
}

addEventListener("DOMContentLoaded", () => {
  const fab = document.createElement("button");
  fab.id = "askfab"; fab.className = "askfab"; fab.type = "button"; fab.setAttribute("aria-expanded", "false"); fab.setAttribute("aria-controls", "askpanel");
  fab.innerHTML = `${I.sparkle}<span>Ask</span>`; fab.title = "Ask the assistant how to do something";
  const panel = document.createElement("section");
  panel.id = "askpanel"; panel.className = "askpanel card"; panel.hidden = true; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Assistant");
  panel.innerHTML = `<div class="askhead"><b class="grow">${I.sparkle} Assistant</b><button class="btn sm ghost" id="askclear" title="Start again">Clear</button><button class="icon-btn" id="askclose" aria-label="Close assistant">${I.x}</button></div>
    <div class="asklog" id="asklog" role="log" aria-live="polite" tabindex="0" aria-label="Conversation"></div>
    <form class="askform" id="askform"><label class="sr" for="askin">Your question</label><input class="input" id="askin" maxlength="500" autocomplete="off" placeholder="e.g. How do I email a recruiter?">
      <button class="btn primary" id="askgo">Send</button></form>`;
  document.body.append(fab, panel);
  fab.onclick = () => askToggle();
  $("#askclose").onclick = () => askToggle(false);
  $("#askclear").onclick = () => { ASK.log = []; askDraw(); $("#askin").focus(); };
  $("#askform").onsubmit = e => { e.preventDefault(); if (ASK.busy) return; const i = $("#askin"), v = i.value; i.value = ""; askSend(v); };   // keep what's typed while an answer is on its way
  panel.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); askToggle(false); } else if (!["Tab", "Enter"].includes(e.key)) e.stopPropagation(); });   // typing here never triggers page shortcuts
});
