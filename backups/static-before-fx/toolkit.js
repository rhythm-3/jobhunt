"use strict";
/* Candidate toolkit UI: interviews, practice, offers, resume health, saving jobs from any site, weekly goal.
   Loaded after app.js and uses its helpers ($, $$, esc, api, toast, I, S, ls, celebrate, go, openDrawer…). */

// ---------------------------------------------------------------- helpers
function modal(title, html, { wide = false } = {}) {
  const m = document.createElement("div"); m.className = "cmdk-scrim modal-scrim tk-modal";
  m.innerHTML = `<div class="cmdk tk-dialog ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="tkh">
      <div class="row tk-head"><h3 id="tkh" class="grow">${esc(title)}</h3><button class="icon-btn" data-close aria-label="Close">${I.x}</button></div>
      <div class="tk-body">${html}</div></div>`;
  document.body.append(m);
  const prev = document.activeElement;
  // Escape is caught at the document (capture phase) while the dialog is open: focus can land on <body>
  // (e.g. after a button disables itself), and Escape must still close the topmost dialog - not the panel under it.
  const onKey = e => {
    if (e.key !== "Escape" || $$(".tk-modal").pop() !== m) return;
    e.stopPropagation(); e.preventDefault(); close();
  };
  const close = () => { document.removeEventListener("keydown", onKey, true); m.remove(); if (prev && prev.focus && document.contains(prev)) prev.focus(); };
  document.addEventListener("keydown", onKey, true);
  m.addEventListener("click", e => { if (e.target === m || e.target.closest("[data-close]")) close(); });
  m.addEventListener("keydown", e => {
    if (e.key === "Tab") {                         // keep focus inside the dialog
      const f = $$('a[href],button:not([disabled]),textarea,input,select', m).filter(x => x.offsetParent);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });
  setTimeout(() => { const f = m.querySelector(".tk-body input:not([type=hidden]),.tk-body textarea,.tk-body select,.tk-body button"); (f || $("[data-close]", m)).focus(); }, 30);
  return { el: m, body: $(".tk-body", m), close };
}
async function download(path, fallbackName) {
  const tok = ls.get("token");
  const r = await fetch("/api" + path, { headers: tok ? { Authorization: "Bearer " + tok } : {} });
  if (!r.ok) { let d = r.statusText; try { d = (await r.json()).detail; } catch {} throw new Error(d); }
  const m = (r.headers.get("content-disposition") || "").match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob());
  a.download = m ? decodeURIComponent(m[1]) : fallbackName; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 3000);
}
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); toast("Copied"); }
  catch { const ta = document.createElement("textarea"); ta.value = t; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove(); toast("Copied"); }
}
const pad = n => String(n).padStart(2, "0");
function toLocalInput(iso) { const d = iso ? new Date(iso) : new Date(Date.now() + 86400000); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }
const fmtWhen = iso => new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
function rel(iso) {
  const s = (new Date(iso) - Date.now()) / 1000, a = Math.abs(s);
  const t = a < 3600 ? `${Math.max(1, Math.round(a / 60))} min` : a < 86400 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} day${Math.round(a / 86400) > 1 ? "s" : ""}`;
  return s >= 0 ? `in ${t}` : `${t} ago`;
}
const LPA = 1e5;
const fmtMoney = (v, cur) => cur === "INR" ? `₹${(v / LPA).toFixed(v % LPA ? 1 : 0)} LPA` : `${({ USD: "$", EUR: "€", GBP: "£", SGD: "S$", AED: "AED " })[cur] || ""}${Math.round(v).toLocaleString()}`;
const ringSvg = (frac, label, size = 64) => `<svg class="miniring" viewBox="0 0 36 36" width="${size}" height="${size}" aria-hidden="true">
  <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--line)" stroke-width="3.5"/><circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--brand)" stroke-width="3.5"
  stroke-linecap="round" stroke-dasharray="${Math.min(1, frac) * 97.4} 97.4" transform="rotate(-90 18 18)"/><text x="18" y="21" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor">${esc(label)}</text></svg>`;

// ---------------------------------------------------------------- weekly goal & streak (dashboard)
function weekStart(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; }
function goalStats(prog) {
  const times = prog.applied_at.map(t => new Date(t)), now = new Date(), ws = weekStart(now);
  const inWeek = (t, start) => t >= start && t < new Date(start.getTime() + 7 * 86400000);
  const thisWeek = times.filter(t => inWeek(t, ws)).length;
  let streak = 0;
  for (let k = thisWeek >= prog.goal ? 0 : 1; k < 60; k++) {
    const start = new Date(ws.getTime() - k * 7 * 86400000);
    if (times.filter(t => inWeek(t, start)).length >= prog.goal) streak++; else break;
  }
  const days = [...Array(7)].map((_, i) => { const d0 = new Date(ws.getTime() + i * 86400000); return { d: d0, n: times.filter(t => t >= d0 && t < new Date(d0.getTime() + 86400000)).length }; });
  return { thisWeek, streak, days };
}
function goalCard(prog, trend) {
  const g = goalStats(prog), max = Math.max(1, ...g.days.map(x => x.n)), today = new Date().getDay();
  return `<section class="card sec goal"><div class="row" style="flex-wrap:nowrap">${ringSvg(g.thisWeek / prog.goal, `${g.thisWeek}/${prog.goal}`, 84)}
      <div class="grow"><h3 style="margin:0">This week</h3><p class="small muted" style="margin:2px 0 0">${g.thisWeek >= prog.goal ? "Goal reached — nice work." : `${prog.goal - g.thisWeek} more application${prog.goal - g.thisWeek > 1 ? "s" : ""} to reach your goal.`}</p>
        ${g.streak ? `<p class="small" style="margin:4px 0 0"><b>${g.streak}-week streak</b> of hitting your goal</p>` : ""}</div></div>
    ${trend ? `<h4 class="agrid-h">Your last 12 weeks</h4>${activityGrid(trend.days, trend.applied)}`
      : `<div class="wbars" role="img" aria-label="Applications per day this week">${g.days.map((x, i) => `<div class="wb ${((i + 1) % 7) === today ? "today" : ""}" title="${x.d.toLocaleDateString([], { weekday: "long" })}: ${x.n}"><i style="height:${x.n ? 8 + 40 * x.n / max : 3}px"></i><span>${"MTWTFSS"[i]}</span></div>`).join("")}</div>`}
    <button class="linkbtn small" id="goalset">Change weekly goal</button></section>`;
}

// ---------------------------------------------------------------- interviews
function showInterviews() {                        // leave any open job panel, then show the Interviews page
  if (S.drawer) { S.drawer = null; const s = $(".scrim:not(.closing)"), d = $(".drawer:not(.closing)");
    [s, d].forEach(x => { if (x) { x.classList.add("closing"); x.classList.remove("on"); setTimeout(() => x.remove(), 450); } }); }
  S.view === "interviews" ? render() : go("interviews");
}
function appOptions(selected) {
  const runs = S.runs.filter(r => r.job && ["submitted", "interview", "offer", "needs_manual", "awaiting_approval", "approved"].includes(r.status));
  return `<option value="">Not in my list / other</option>${runs.map(r => `<option value="${esc(r.id)}" ${r.id === selected ? "selected" : ""}>${esc(r.job.company)} — ${esc(r.job.title.slice(0, 60))}</option>`).join("")}`;
}
function interviewForm(iv = {}, suggestion = null) {
  const s = suggestion || {};
  const m = modal(iv.id ? "Edit interview" : "Schedule an interview", `
    <div class="formgrid">
      <label class="span2">Application<select class="select" id="ivrun">${appOptions(iv.run_id || s.run_id)}</select></label>
      <label>Company<input class="input" id="ivco" value="${esc(iv.company || s.company || "")}" required></label>
      <label>Role<input class="input" id="ivrole" value="${esc(iv.role || s.role || "")}"></label>
      <label>Date & time (your time zone)<input class="input" type="datetime-local" id="ivwhen" value="${toLocalInput(iv.starts_at || (s.times && s.times[0]))}" required></label>
      <label>Length<select class="select" id="ivdur">${[20, 30, 45, 60, 90, 120].map(n => `<option ${n === (iv.duration_min || 45) ? "selected" : ""} value="${n}">${n} min</option>`).join("")}</select></label>
      <label>Type<select class="select" id="ivkind">${["phone", "video", "technical", "onsite", "hr", "final", "other"].map(k => `<option ${k === (iv.kind || "video") ? "selected" : ""}>${k}</option>`).join("")}</select></label>
      <label>With<input class="input" id="ivwith" value="${esc(iv.with_whom || s.with_whom || "")}" placeholder="e.g. Hiring manager, Priya S."></label>
      <label class="span2">Meeting link<input class="input" id="ivlink" value="${esc(iv.link || s.link || "")}" placeholder="https://…"></label>
      <label class="span2">Location (if in person)<input class="input" id="ivloc" value="${esc(iv.location || "")}"></label>
      <label class="span2">Notes<textarea class="textarea" id="ivnotes" style="min-height:80px">${esc(iv.notes || "")}</textarea></label>
    </div>
    ${s.times && s.times.length > 1 ? `<div class="small muted" style="margin-top:8px">Times mentioned in the email: ${s.times.map(t => `<button class="chip linkchip" data-t="${esc(t)}">${esc(fmtWhen(t))}</button>`).join(" ")}</div>` : ""}
    ${s.booking_link ? `<div class="small muted" style="margin-top:6px">The recruiter sent a booking page — pick a slot there first: <a href="${esc(s.booking_link)}" target="_blank" rel="noopener noreferrer">open booking page ↗</a></div>` : ""}
    <div class="row" style="margin-top:14px"><span class="grow"></span><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="ivsave">${iv.id ? "Save" : "Schedule"}</button></div>`);
  const b = m.body;
  $("#ivrun", b).onchange = e => { const r = S.runs.find(x => x.id === e.target.value); if (r) { $("#ivco", b).value = r.job.company; $("#ivrole", b).value = r.job.title; } };
  $$("[data-t]", b).forEach(x => x.onclick = () => { $("#ivwhen", b).value = toLocalInput(x.dataset.t); });
  $("#ivsave", b).onclick = async () => {
    const when = $("#ivwhen", b).value;
    if (!$("#ivco", b).value.trim() || !when) return toast("Company and date are required");
    const body = { run_id: $("#ivrun", b).value || null, company: $("#ivco", b).value.trim(), role: $("#ivrole", b).value.trim(),
      starts_at: new Date(when).toISOString(), duration_min: +$("#ivdur", b).value, kind: $("#ivkind", b).value, with_whom: $("#ivwith", b).value.trim(),
      link: $("#ivlink", b).value.trim(), location: $("#ivloc", b).value.trim(), notes: $("#ivnotes", b).value };
    try { await api(iv.id ? `/interviews/${iv.id}` : "/interviews", { method: iv.id ? "PUT" : "POST", body });
      m.close(); toast(iv.id ? "Interview updated" : "Interview scheduled — add it to your calendar from Interviews"); S.ivTab = "upcoming"; showInterviews(); }
    catch (e) { toast(e.message, 6000); }
  };
  return m;
}
async function thankYou(iv) {
  const m = modal(`Thank-you note — ${iv.company}`, `
    <p class="small muted" style="margin-top:0">Send within 24 hours. Mention one specific thing you discussed — that's what makes it memorable.</p>
    <label>What did you talk about? (optional)<input class="input" id="tytopics" placeholder="e.g. how the team handles detection engineering at scale"></label>
    <div class="row" style="margin:8px 0"><button class="btn sm" id="tydraft">${I.sparkle}Draft it</button><span class="small muted" id="tyhow"></span></div>
    <label>To<input class="input" id="tyto" placeholder="recruiter@company.com"></label>
    <textarea class="textarea" id="tybody" style="margin-top:8px;min-height:190px" aria-label="Message"></textarea>
    <div class="row" style="margin-top:10px"><span class="small muted grow" id="tynote"></span><button class="btn" id="tycopy">Copy</button><button class="btn success" id="tysend">${I.send}Send</button></div>`);
  const b = m.body;
  const draft = async () => {
    $("#tybody", b).value = "Drafting…";
    try { const r = await api(`/interviews/${iv.id}/thank-you/draft`, { method: "POST", body: { topics: $("#tytopics", b).value } });
      $("#tybody", b).value = r.body; if (r.to && !$("#tyto", b).value) $("#tyto", b).value = r.to;
      $("#tyhow", b).textContent = r.method === "template" ? "template" : "by " + r.method;
      $("#tynote", b).textContent = r.in_thread ? "Replies in the same thread as the recruiter's email." : ""; }
    catch (e) { toast(e.message); }
  };
  $("#tydraft", b).onclick = draft; $("#tycopy", b).onclick = () => copyText($("#tybody", b).value);
  $("#tysend", b).onclick = async e => {
    const body = $("#tybody", b).value;
    if (/\[[^\]\n]{2,80}\]/.test(body)) return toast("Fill in the [placeholder] first");
    const sendBtn = e.currentTarget; sendBtn.disabled = true;
    try { const r = await api(`/interviews/${iv.id}/thank-you/send`, { method: "POST", body: { body, to: $("#tyto", b).value.trim() } });
      m.close(); celebrate(r.dry_run ? "Thank-you approved (practice mode)" : "Thank-you sent"); render(); }
    catch (x) { toast(x.message, 6000); sendBtn.disabled = false; }
  };
  draft();
}
function ivCard(iv, past) {
  const d = new Date(iv.starts_at);
  const act = [];
  if (!past && iv.link) act.push(`<a class="btn sm primary" href="${esc(iv.link)}" target="_blank" rel="noopener noreferrer">Join</a>`);
  if (iv.run_id) act.push(`<button class="btn sm" data-ivprep="${esc(iv.run_id)}">Prep kit</button>`);
  if (!past) act.push(`<button class="btn sm" data-ivpractice="${esc(iv.id)}">Practice</button>`, `<button class="btn sm" data-ivics="${esc(iv.id)}">${I.cal}Calendar</button>`);
  if (past && iv.status !== "cancelled") act.push(iv.thank_you_sent_at ? `<span class="chip ok">Thank-you sent</span>` : `<button class="btn sm primary" data-ivty="${esc(iv.id)}">Send thank-you</button>`);
  if (past && iv.run_id && iv.run_status !== "offer") act.push(`<button class="btn sm" data-ivoffer="${esc(iv.run_id)}">Got an offer?</button>`);
  act.push(`<button class="btn sm ghost" data-ivedit="${esc(iv.id)}">Edit</button>`);
  if (iv.status === "scheduled") act.push(`<button class="btn sm ghost" data-ivdone="${esc(iv.id)}">${past ? "Mark done" : "Cancel"}</button>`);
  return `<div class="card ivcard ${iv.status}"><div class="ivdate" aria-hidden="true"><b>${d.getDate()}</b><span>${d.toLocaleDateString([], { month: "short" })}</span></div>
    <div class="grow" style="min-width:0"><h3>${esc(iv.company)}${iv.role ? ` <span class="muted" style="font-weight:400">· ${esc(iv.role)}</span>` : ""}</h3>
      <div class="small muted">${esc(fmtWhen(iv.starts_at))} · ${iv.duration_min} min · ${esc(iv.kind)}${iv.with_whom ? " · with " + esc(iv.with_whom) : ""}</div>
      <div class="small ${!past && d - Date.now() < 86400000 ? "soon" : ""}">${iv.status === "cancelled" ? "Cancelled" : esc(rel(iv.starts_at))}${iv.status === "done" ? " · done" : ""}</div></div>
    <div class="row ivact">${act.join("")}</div></div>`;
}
async function vInterviews(c) {
  $("#pageactions").innerHTML = `<button class="btn" id="pa-offer">Add an offer</button><button class="btn primary" id="pa-iv">${I.cal}Schedule interview</button>`;
  $("#pa-iv").onclick = () => interviewForm(); $("#pa-offer").onclick = () => offerForm();
  const [ivs, offers] = await Promise.all([api("/interviews"), api("/offers")]);
  const now = Date.now();
  const upcoming = ivs.filter(i => i.status === "scheduled" && new Date(i.starts_at).getTime() + i.duration_min * 60000 > now).sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at));
  const past = ivs.filter(i => !upcoming.includes(i)).sort((a, b) => new Date(b.starts_at) - new Date(a.starts_at));
  const tabs = [["upcoming", "Upcoming", upcoming.length], ["past", "Past", past.length], ["practice", "Practice", ""], ["offers", "Offers", offers.length]];
  S.ivTab = S.ivTab || "upcoming";
  c.innerHTML = `<div class="view"><div class="tabsbar" role="tablist" aria-label="Interviews">${tabs.map(([k, l, n]) => `<button role="tab" aria-selected="${S.ivTab === k}" data-ivt="${k}">${l}${n !== "" ? `<span class="n">${n}</span>` : ""}</button>`).join("")}</div><div id="ivbody"></div></div>`;
  $$("[data-ivt]", c).forEach(b => b.onclick = () => { S.ivTab = b.dataset.ivt; vInterviews(c); });
  const body = $("#ivbody", c);
  if (S.ivTab === "upcoming" || S.ivTab === "past") {
    const list = S.ivTab === "upcoming" ? upcoming : past;
    body.innerHTML = list.length ? `<div class="list">${list.map(i => ivCard(i, S.ivTab === "past")).join("")}</div>`
      : `<div class="card empty big">${EMPTY.interviews}<b>${S.ivTab === "upcoming" ? "No interviews scheduled" : "No past interviews yet"}</b>
         <span>${S.ivTab === "upcoming" ? "When a recruiter invites you, open the email in Inbox and choose “Add to interviews” — or schedule one here." : ""}</span>
         ${S.ivTab === "upcoming" ? `<button class="btn primary" id="ivnew">${I.cal}Schedule interview</button>` : ""}</div>`;
    const nb = $("#ivnew", body); if (nb) nb.onclick = () => interviewForm();
    const byId = id => ivs.find(i => i.id === id);
    $$("[data-ivprep]", body).forEach(b => b.onclick = () => { openDrawer(b.dataset.ivprep); setTimeout(() => { const t = $('.drawer [data-tab="prep"]'); t && t.click(); }, 900); });
    $$("[data-ivpractice]", body).forEach(b => b.onclick = () => { S.practiceRun = byId(b.dataset.ivpractice).run_id; S.ivTab = "practice"; vInterviews(c); });
    $$("[data-ivics]", body).forEach(b => b.onclick = () => download(`/interviews/${b.dataset.ivics}/ics`, "interview.ics").then(() => toast("Calendar file downloaded — open it to add the interview")).catch(e => toast(e.message)));
    $$("[data-ivty]", body).forEach(b => b.onclick = () => thankYou(byId(b.dataset.ivty)));
    $$("[data-ivedit]", body).forEach(b => b.onclick = () => interviewForm(byId(b.dataset.ivedit)));
    $$("[data-ivoffer]", body).forEach(b => b.onclick = () => { const r = S.runs.find(x => x.id === b.dataset.ivoffer); offerForm({ run_id: b.dataset.ivoffer, company: r && r.job.company, role: r && r.job.title }); });
    $$("[data-ivdone]", body).forEach(b => b.onclick = async () => {
      const iv = byId(b.dataset.ivdone), isPast = S.ivTab === "past";
      if (!isPast && !confirm(`Cancel the ${iv.company} interview?`)) return;
      await api(`/interviews/${iv.id}`, { method: "PUT", body: { status: isPast ? "done" : "cancelled" } }); toast(isPast ? "Marked done" : "Interview cancelled"); vInterviews(c);
    });
  } else if (S.ivTab === "practice") {
    await practiceTab(body, upcoming);
  } else {
    await offersTab(body, offers);
  }
}

// ---------------------------------------------------------------- practice
async function practiceTab(body, upcoming) {
  const runIds = [...new Set([S.practiceRun, ...upcoming.map(i => i.run_id)].filter(Boolean))];
  const infos = await Promise.all(runIds.map(id => api(`/practice?run_id=${id}`).then(x => ({ id, ...x })).catch(() => null)));
  const general = await api("/practice");
  const groups = infos.filter(x => x && x.prep.length).map(x => { const r = S.runs.find(y => y.id === x.id); return { run_id: x.id, label: r ? `${r.job.company} prep kit` : "Prep kit", qs: x.prep }; });
  groups.push({ run_id: null, label: "Common questions", qs: general.bank });
  const missingKits = runIds.filter(id => !groups.some(g => g.run_id === id));
  body.innerHTML = `<div class="practice-layout"><aside class="card sec qpick"><h3>Pick a question</h3>
      ${groups.map((g, gi) => `<div class="qgroup"><div class="navlabel">${esc(g.label)}</div>${g.qs.map((q, qi) => `<button class="qbtn" data-g="${gi}" data-q="${qi}">${esc(q)}</button>`).join("")}</div>`).join("")}
      ${missingKits.length ? `<p class="small muted">No prep kit yet for ${missingKits.length} upcoming interview(s) — open the job and generate one in “Interview prep”.</p>` : ""}
      <div class="qgroup"><div class="navlabel">Your own question</div><input class="input" id="ownq" placeholder="Type a question and press Enter"></div></aside>
    <div id="ppanel"><div class="card empty big">${EMPTY.practice}<b>Practise out loud or in writing</b><span>Pick a question. You'll get feedback on structure (STAR), evidence and length — and which of your real experiences to use.</span></div></div></div>`;
  const open = (q, run_id) => { $$(".qbtn", body).forEach(b => b.removeAttribute("aria-current")); practicePanel($("#ppanel", body), q, run_id); };
  $$(".qbtn", body).forEach(b => b.onclick = () => { b.setAttribute("aria-current", "true"); const g = groups[+b.dataset.g]; open(g.qs[+b.dataset.q], g.run_id); });
  $("#ownq", body).onkeydown = e => { if (e.key === "Enter" && e.target.value.trim()) open(e.target.value.trim(), S.practiceRun || null); };
}
function practicePanel(box, question, run_id) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  box.innerHTML = `<div class="card sec practice"><div class="small muted">Question</div><h3 style="margin:2px 0 12px">${esc(question)}</h3>
    <div class="row"><button class="btn sm" id="ptimer">▶ Start timer</button><span class="timer" id="ptime" aria-live="off">0:00</span>
      ${SR ? `<button class="btn sm" id="pdict" title="Uses your browser's speech service">🎙 Dictate</button>` : ""}<span class="grow"></span><span class="small muted">Aim for 1½–2 minutes</span></div>
    <textarea class="textarea" id="pans" style="margin-top:10px;min-height:200px" placeholder="Answer as you would in the interview. Tip: Situation → Task → Action (what YOU did) → Result (with a number if you have one)." aria-label="Your answer"></textarea>
    <div class="row" style="margin-top:10px"><span class="small muted grow" id="pwc">0 words</span><button class="btn primary" id="pgo">${I.sparkle}Get feedback</button></div>
    <div id="pfb"></div></div>`;
  const ta = $("#pans", box), wc = () => $("#pwc", box).textContent = `${ta.value.trim().split(/\s+/).filter(Boolean).length} words`;
  ta.oninput = wc; ta.focus();
  let t0 = null, tick = null;
  $("#ptimer", box).onclick = e => {
    if (tick) { clearInterval(tick); tick = null; e.currentTarget.textContent = "▶ Start timer"; return; }
    t0 = Date.now(); e.currentTarget.textContent = "■ Stop";
    tick = setInterval(() => { if (!document.contains(box)) return clearInterval(tick); const s = Math.round((Date.now() - t0) / 1000); $("#ptime", box).textContent = `${Math.floor(s / 60)}:${pad(s % 60)}`; }, 500);
  };
  const dict = $("#pdict", box);
  if (dict) {
    let rec = null;
    dict.onclick = () => {
      if (rec) { rec.stop(); return; }
      rec = new SR(); rec.continuous = true; rec.interimResults = false; rec.lang = navigator.language || "en-IN";
      rec.onresult = ev => { for (let i = ev.resultIndex; i < ev.results.length; i++) if (ev.results[i].isFinal) ta.value += (ta.value && !/\s$/.test(ta.value) ? " " : "") + ev.results[i][0].transcript.trim(); wc(); };
      rec.onend = () => { rec = null; dict.textContent = "🎙 Dictate"; };
      rec.onerror = ev => toast("Dictation: " + ev.error);
      rec.start(); dict.textContent = "■ Stop dictating";
    };
  }
  $("#pgo", box).onclick = async e => {
    const b = e.currentTarget; b.disabled = true; b.innerHTML = `<span class="spin" style="animation:spin .9s linear infinite">${I.refresh}</span>Reviewing…`;
    try { const f = await api("/practice", { method: "POST", body: { question, answer: ta.value, run_id } }); $("#pfb", box).innerHTML = feedbackHtml(f); $("#pfb", box).scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    catch (x) { toast(x.message); }
    b.disabled = false; b.innerHTML = `${I.sparkle}Get feedback`; b.focus();       // a disabled button drops focus: give it back
  };
}
function feedbackHtml(f) {
  const part = (k, l) => `<span class="chip ${f.parts[k] ? "ok" : "miss"}">${f.parts[k] ? "✓" : "✗"} ${l}</span>`;
  return `<div class="fbk"><div class="row" style="flex-wrap:nowrap">${ringSvg(f.score / 10, `${f.score}/10`, 70)}
      <div class="grow"><div class="row" style="gap:6px">${part("situation", "Situation")}${part("action", "Your action")}${part("result", "Result")}<span class="chip ${f.metrics ? "ok" : ""}">${f.metrics ? "✓ numbers" : "no numbers"}</span></div>
      <div class="small muted" style="margin-top:6px">${f.words} words · about ${Math.floor(f.seconds / 60)} min ${f.seconds % 60}s spoken · “I” ×${f.i}, “we” ×${f.we}</div></div></div>
    <div class="fcols"><div><h4>What worked</h4><ul>${f.strengths.map(s => `<li>${esc(s)}</li>`).join("") || "<li class='muted'>—</li>"}</ul></div>
      <div><h4>To improve</h4><ul>${f.improve.map(s => `<li>${esc(s)}</li>`).join("") || "<li class='muted'>Nothing major — practise saying it out loud.</li>"}</ul></div></div>
    ${f.evidence.length ? `<h4>Real experience you could use</h4><ul class="evid">${f.evidence.map(b => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}
    ${f.coach ? `<h4>Coach notes <span class="small muted" style="font-weight:400">(${esc(f.method)})</span></h4><ul>${[...f.coach.strengths.map(s => "✓ " + s), ...f.coach.improvements.map(s => "→ " + s)].map(s => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}</div>`;
}

// ---------------------------------------------------------------- offers
function offerForm(o = {}) {
  const cur = o.currency || "INR", k = cur === "INR" ? LPA : 1, unit = cur === "INR" ? "LPA" : "per year";
  const v = x => x ? +(x / k).toFixed(2) : "";
  const r = o.ratings || {};
  const m = modal(o.id ? `Edit offer — ${o.company}` : "Add an offer", `
    <div class="formgrid">
      <label class="span2">Application<select class="select" id="ofrun">${appOptions(o.run_id)}</select></label>
      <label>Company<input class="input" id="ofco" value="${esc(o.company || "")}"></label><label>Role<input class="input" id="ofrole" value="${esc(o.role || "")}"></label>
      <label>Currency<select class="select" id="ofcur">${["INR", "USD", "EUR", "GBP", "SGD", "AED"].map(x => `<option ${x === cur ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <label>Base salary <span class="unit">(${unit})</span><input class="input" type="number" min="0" step="0.1" id="ofbase" value="${v(o.base)}"></label>
      <label>Annual bonus <span class="unit">(${unit})</span><input class="input" type="number" min="0" step="0.1" id="ofbonus" value="${v(o.bonus)}"></label>
      <label>Equity per year <span class="unit">(${unit}, your estimate)</span><input class="input" type="number" min="0" step="0.1" id="ofeq" value="${v(o.equity_per_year)}"></label>
      <label>Joining bonus <span class="unit">(${unit})</span><input class="input" type="number" min="0" step="0.1" id="ofjoin" value="${v(o.joining_bonus)}"></label>
      <label>Work mode<select class="select" id="ofmode">${["remote", "hybrid", "onsite"].map(x => `<option ${x === (o.work_mode || "hybrid") ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <label>Location<input class="input" id="ofloc" value="${esc(o.location || "")}"></label>
      <label>Notice period (days)<input class="input" type="number" min="0" id="ofnotice" value="${o.notice_days || ""}"></label>
      <label>Decision deadline<input class="input" type="date" id="ofdead" value="${esc(o.deadline || "")}"></label>
      <label class="span2">Benefits<input class="input" id="ofben" value="${esc(o.benefits || "")}" placeholder="e.g. health cover for parents, learning budget"></label>
      <fieldset class="span2 rates"><legend>How do you feel about… (1 = poor, 5 = great)</legend>${[["growth", "Growth"], ["team", "Team & manager"], ["work_life", "Work-life balance"], ["learning", "Learning"]]
        .map(([k2, l]) => `<label>${l}<select class="select" data-rate="${k2}">${[1, 2, 3, 4, 5].map(n => `<option ${n === (r[k2] || 3) ? "selected" : ""}>${n}</option>`).join("")}</select></label>`).join("")}</fieldset>
      <label class="span2">Notes<textarea class="textarea" id="ofnotes" style="min-height:70px">${esc(o.notes || "")}</textarea></label>
    </div><div class="row" style="margin-top:14px"><span class="grow"></span><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="ofsave">${o.id ? "Save" : "Add offer"}</button></div>`, { wide: true });
  const b = m.body;
  $("#ofrun", b).onchange = e => { const x = S.runs.find(y => y.id === e.target.value); if (x) { $("#ofco", b).value = x.job.company; $("#ofrole", b).value = x.job.title; } };
  $("#ofcur", b).onchange = e => $$(".unit", b).forEach((u, i) => u.textContent = `(${e.target.value === "INR" ? "LPA" : "per year"}${i === 2 ? ", your estimate" : ""})`);
  $("#ofsave", b).onclick = async () => {
    const c2 = $("#ofcur", b).value, kk = c2 === "INR" ? LPA : 1, num = id => Math.round((+$(id, b).value || 0) * kk);
    if (!$("#ofco", b).value.trim() || !num("#ofbase")) return toast("Company and base salary are required");
    const ratings = {}; $$("[data-rate]", b).forEach(s => ratings[s.dataset.rate] = +s.value);
    const body = { run_id: $("#ofrun", b).value || null, company: $("#ofco", b).value.trim(), role: $("#ofrole", b).value.trim(), currency: c2,
      base: num("#ofbase"), bonus: num("#ofbonus"), equity_per_year: num("#ofeq"), joining_bonus: num("#ofjoin"), work_mode: $("#ofmode", b).value,
      location: $("#ofloc", b).value.trim(), notice_days: +$("#ofnotice", b).value || 0, deadline: $("#ofdead", b).value, benefits: $("#ofben", b).value.trim(),
      notes: $("#ofnotes", b).value, ratings };
    try { await api(o.id ? `/offers/${o.id}` : "/offers", { method: o.id ? "PUT" : "POST", body }); m.close(); if (!o.id) celebrate("Congratulations on the offer!");
      S.ivTab = "offers"; showInterviews(); }
    catch (e) { toast(e.message, 6000); }
  };
}
const OFFER_W = () => { try { return { pay: 40, growth: 20, team: 15, work_life: 15, learning: 10, ...JSON.parse(ls.get("offerW") || "{}") }; } catch { return { pay: 40, growth: 20, team: 15, work_life: 15, learning: 10 }; } };
function offerScores(offers, w) {
  const tot = Object.values(w).reduce((a, b) => a + b, 0) || 1;
  return offers.map(o => {
    const same = offers.filter(x => x.currency === o.currency), max = Math.max(...same.map(x => x.recurring)) || 1;
    const pay = 5 * o.recurring / max;
    const s = (w.pay * pay + w.growth * o.ratings.growth + w.team * o.ratings.team + w.work_life * o.ratings.work_life + w.learning * o.ratings.learning) / tot;
    return Math.round(s / 5 * 100);
  });
}
async function offersTab(body, offers) {
  if (!offers.length) {
    body.innerHTML = `<div class="card empty big">${EMPTY.offers}<b>No offers yet</b><span>When one arrives, add it here to compare packages side by side, check it against the market and draft a negotiation email.</span><button class="btn primary" id="ofnew">Add an offer</button></div>`;
    $("#ofnew", body).onclick = () => offerForm(); return;
  }
  const w = OFFER_W();
  const markets = await Promise.all(offers.map(o => api(`/offers/market?role=${encodeURIComponent(o.role || "")}`).catch(() => ({ n: 0 }))));
  const draw = () => {
    const sc = offerScores(offers, w), best = Math.max(...sc);
    const row = (label, f, hi) => { const vals = offers.map(f); return `<tr><th scope="row">${label}</th>${vals.map((x, i) => `<td class="${hi && hi(i) ? "best" : ""}">${x}</td>`).join("")}</tr>`; };
    const maxBy = key => { const m = Math.max(...offers.map(o => o[key])); return i => offers.length > 1 && offers[i][key] === m && m > 0; };
    body.innerHTML = `<div class="card sec"><h3>What matters to you</h3><p class="small muted" style="margin-top:0">Weights for the overall score. Pay is compared across offers in the same currency.</p>
        <div class="weights">${[["pay", "Pay"], ["growth", "Growth"], ["team", "Team"], ["work_life", "Work-life"], ["learning", "Learning"]].map(([k, l]) =>
          `<label>${l} <span class="rangeval">${w[k]}</span><input type="range" min="0" max="60" step="5" value="${w[k]}" data-w="${k}"></label>`).join("")}</div></div>
      <div class="cmpwrap"><table class="cmp"><thead><tr><th></th>${offers.map((o, i) => `<th scope="col"><div class="row" style="flex-wrap:nowrap">${avatar(o.company)}<div><b>${esc(o.company)}</b><div class="small muted">${esc(o.role || "")}</div></div></div>
          <div class="oscore ${sc[i] === best && offers.length > 1 ? "bestscore" : ""}">${sc[i]}<small>/100</small>${sc[i] === best && offers.length > 1 ? ` <span class="chip ok">Best fit</span>` : ""}</div></th>`).join("")}</tr></thead><tbody>
        ${row("Status", o => `<select class="select sm" data-ost="${o.id}">${["considering", "negotiating", "accepted", "declined"].map(s => `<option ${s === o.status ? "selected" : ""}>${s}</option>`).join("")}</select>`)}
        ${row("Base salary", o => fmtMoney(o.base, o.currency), maxBy("base"))}
        ${row("Bonus", o => o.bonus ? fmtMoney(o.bonus, o.currency) : "—")}
        ${row("Equity / year", o => o.equity_per_year ? fmtMoney(o.equity_per_year, o.currency) : "—")}
        ${row("Yearly total", o => `<b>${fmtMoney(o.recurring, o.currency)}</b>`, maxBy("recurring"))}
        ${row("Joining bonus", o => o.joining_bonus ? fmtMoney(o.joining_bonus, o.currency) : "—")}
        ${row("First-year total", o => fmtMoney(o.first_year, o.currency), maxBy("first_year"))}
        ${row("Market check", (o, i) => { const mk = markets[i]; if (o.currency !== "INR" || !mk || !mk.median) return `<span class="small muted">not enough data</span>`;
            const diff = Math.round((o.base / LPA / mk.median - 1) * 100);
            return `<span class="chip ${diff >= 0 ? "ok" : "warn"}">${diff >= 0 ? "+" : ""}${diff}%</span><div class="small muted">vs median ₹${mk.median} LPA of ${mk.n} listings (${esc(mk.basis)})</div>`; })}
        ${row("Work mode", o => esc(o.work_mode) + (o.location ? ` · ${esc(o.location)}` : ""))}
        ${row("Notice period", o => o.notice_days ? `${o.notice_days} days` : "—")}
        ${row("Decide by", o => o.deadline ? `${esc(new Date(o.deadline + "T00:00").toLocaleDateString([], { day: "numeric", month: "short" }))} <span class="small muted">(${esc(rel(o.deadline + "T23:59"))})</span>` : "—")}
        ${row("Growth · Team · Balance · Learning", o => `${o.ratings.growth} · ${o.ratings.team} · ${o.ratings.work_life} · ${o.ratings.learning}`)}
        ${row("Benefits", o => esc(o.benefits || "—"))}
        <tr><th></th>${offers.map(o => `<td><div class="row"><button class="btn sm primary" data-oneg="${o.id}">Negotiate</button><button class="btn sm" data-oedit="${o.id}">Edit</button><button class="btn sm ghost danger" data-odel="${o.id}">Delete</button></div></td>`).join("")}</tr>
      </tbody></table></div>
      <p class="small muted">Market check uses salaries stated in your own job list (mostly Glassdoor estimates) — a rough guide, not a quote.</p>`;
    $$("[data-w]", body).forEach(s => s.oninput = () => { w[s.dataset.w] = +s.value; ls.set("offerW", JSON.stringify(w)); draw(); $(`[data-w="${s.dataset.w}"]`, body).focus(); });
    $$("[data-ost]", body).forEach(s => s.onchange = async () => { await api(`/offers/${s.dataset.ost}`, { method: "PUT", body: { status: s.value } }); const o = offers.find(x => x.id === s.dataset.ost); o.status = s.value; if (s.value === "accepted") celebrate("Offer accepted — congratulations!"); });
    $$("[data-oedit]", body).forEach(b => b.onclick = () => offerForm(offers.find(x => x.id === b.dataset.oedit)));
    $$("[data-odel]", body).forEach(b => b.onclick = async () => { if (!confirm("Delete this offer?")) return; await api(`/offers/${b.dataset.odel}`, { method: "DELETE" }); render(); });
    $$("[data-oneg]", body).forEach(b => b.onclick = () => negotiate(offers.find(x => x.id === b.dataset.oneg), markets[offers.findIndex(x => x.id === b.dataset.oneg)]));
  };
  draw();
}
function negotiate(o, mk) {
  const k = o.currency === "INR" ? LPA : 1, unit = o.currency === "INR" ? "LPA" : o.currency;
  const suggest = +((o.base / k) * 1.12).toFixed(1);
  const m = modal(`Negotiate — ${o.company}`, `
    <p class="small muted" style="margin-top:0">A polite, specific ask usually works best. Everything in the email comes from what you entered — nothing is invented.</p>
    <div class="formgrid"><label>Current base<input class="input" value="${esc(fmtMoney(o.base, o.currency))}" disabled></label>
      <label>Ask for base (${unit})<input class="input" type="number" step="0.1" id="ngt" value="${suggest}"></label></div>
    ${mk && mk.median ? `<p class="small">Market in your job list: median ₹${mk.median} LPA, top quarter ₹${mk.p75} LPA (${mk.n} listings).</p>` : ""}
    <fieldset class="rates"><legend>Reasons to mention</legend>
      <label class="row"><input type="checkbox" value="experience" checked> Your hands-on experience</label>
      <label class="row"><input type="checkbox" value="scope"> The scope of the role</label>
      <label class="row"><input type="checkbox" value="market"> Market data for similar roles</label>
      <label class="row"><input type="checkbox" id="ngc"> Mention my other offer (only if it's higher)</label></fieldset>
    <div class="row" style="margin:10px 0"><button class="btn primary" id="ngo">${I.sparkle}Draft the email</button></div>
    <div id="ngw"></div><textarea class="textarea" id="ngb" style="min-height:220px" aria-label="Email"></textarea>
    <div class="row" style="margin-top:10px"><span class="grow small muted">Copy it into your email to the recruiter.</span><button class="btn" id="ngcopy">Copy</button></div>`);
  const b = m.body;
  $("#ngo", b).onclick = async () => {
    const reasons = $$('fieldset input[type=checkbox][value]', b).filter(x => x.checked).map(x => x.value);
    try { const r = await api(`/offers/${o.id}/negotiation`, { method: "POST", body: { target_base: Math.round((+$("#ngt", b).value || 0) * k), mention_competing: $("#ngc", b).checked, reasons } });
      $("#ngb", b).value = r.body; $("#ngw", b).innerHTML = r.warnings.map(w => `<div class="warnbox">${esc(w)}</div>`).join("");
      if (o.status === "considering") api(`/offers/${o.id}`, { method: "PUT", body: { status: "negotiating" } }); }
    catch (e) { toast(e.message, 6000); }
  };
  $("#ngcopy", b).onclick = () => copyText($("#ngb", b).value);
}

// ---------------------------------------------------------------- resume health (Settings › Profile)
async function healthCard(box, onGoto) {
  box.innerHTML = '<div class="card sec"><div class="sk" style="height:120px"></div></div>';
  let h;
  try { h = await api("/profile/health"); } catch (e) { box.innerHTML = ""; return; }
  S.health = h;
  requestAnimationFrame(() => { const m = $("#hmore", box); if (m) m.onclick = () => { const ul = $(".issues", box), open = ul.classList.toggle("short") === false;
    m.setAttribute("aria-expanded", String(open)); m.textContent = open ? "Show fewer" : `Show all ${top.length} suggestions`; }; });
  const canRewrite = S.agents && S.agents.tailoring.provider !== "rules";
  const top = h.issues.filter(i => i.severity !== "info").slice(0, 8), info = h.issues.filter(i => i.severity === "info");
  box.innerHTML = `<section class="card sec health"><div class="row" style="flex-wrap:nowrap;align-items:flex-start">${ringSvg(h.score / 100, String(h.score), 76)}
      <div class="grow"><h3 style="margin:0">Resume health · ${esc(h.grade)}</h3><p class="small muted" style="margin:2px 0 8px">Checked against your saved profile and what employers in your job list ask for.</p>
        <div class="hbars">${h.categories.map(c => `<div><span>${esc(c.name)}</span><i><b style="width:${Math.round(c.score / c.max * 100)}%"></b></i><em>${Math.round(c.score)}/${c.max}</em></div>`).join("")}</div></div></div>
    ${h.add_skills.length ? `<div class="okbox">Used in your bullets but not in your skills list: ${h.add_skills.map(s => `<button class="chip linkchip" data-addsk="${esc(s)}">+ ${esc(s)}</button>`).join(" ")}</div>` : ""}
    ${top.length ? `<ul class="issues short">${top.map((i, n) => `<li class="${i.severity}"><span class="sev">${i.severity === "fix" ? "Fix" : "Improve"}</span><div class="grow"><div>${esc(i.text)}</div>
        ${i.target && i.target.text ? `<div class="small muted qt">“${esc(i.target.text.slice(0, 110))}${i.target.text.length > 110 ? "…" : ""}”</div>` : ""}</div>
        ${i.target && i.target.text ? `<div class="row"><button class="btn sm ghost" data-goto="${n}">Edit</button>${canRewrite ? `<button class="btn sm" data-rw="${n}">${I.sparkle}Suggest</button>` : ""}</div>` : ""}</li>`).join("")}</ul>${top.length > 3 ? `<button class="linkbtn small" id="hmore" aria-expanded="false">Show all ${top.length} suggestions</button>` : ""}`
      : '<p class="okbox">No fixes needed — nice work.</p>'}
    ${info.length ? `<details><summary class="small">${info.length} more note${info.length > 1 ? "s" : ""}</summary><ul class="issues">${info.map(i => `<li class="info"><span class="sev">Note</span><div>${esc(i.text)}</div></li>`).join("")}</ul></details>` : ""}
    </section>`;
  $$("[data-goto]", box).forEach(b => b.onclick = () => onGoto(top[+b.dataset.goto].target));
  $$("[data-addsk]", box).forEach(b => b.onclick = () => onGoto({ addSkill: b.dataset.addsk }));
  $$("[data-rw]", box).forEach(b => b.onclick = async () => {
    const t = top[+b.dataset.rw].target; b.disabled = true; b.innerHTML = `<span class="spin" style="animation:spin .9s linear infinite">${I.refresh}</span>`;
    try { const r = await api("/profile/improve-bullet", { method: "POST", body: { bullet: t.text } });
      if (!r.options.length) { toast(r.note || "No safe rewrite found — the suggestions changed facts, so they were discarded"); return; }
      const m = modal("Suggested rewrites", `<p class="small muted" style="margin-top:0">Checked: no new numbers, tools or claims. Pick one or keep yours.</p>
        <div class="qt">Original: ${esc(t.text)}</div>${r.options.map((o, i) => `<div class="card sec rwopt"><p style="margin:0 0 8px">${esc(o)}</p><button class="btn sm primary" data-use="${i}">Use this</button></div>`).join("")}`);
      $$("[data-use]", m.body).forEach(u => u.onclick = () => { m.close(); onGoto({ ...t, replace: r.options[+u.dataset.use] }); }); }
    catch (e) { toast(e.message); }
    finally { b.disabled = false; b.innerHTML = `${I.sparkle}Suggest`; }
  });
}

// ---------------------------------------------------------------- save jobs from any website
function bookmarkletHref() {
  const origin = location.origin;
  const js = `(()=>{try{const P=h=>new DOMParser().parseFromString(h,'text/html').body.textContent||'';let J=null;for(const s of document.querySelectorAll('script[type="application/ld+json"]')){try{const d=JSON.parse(s.textContent);for(const x of [].concat(d['@graph']||d)){const t=x&&x['@type'];if(t==='JobPosting'||(Array.isArray(t)&&t.includes('JobPosting'))){J=x;break}}}catch(e){}if(J)break}const Q=(...a)=>{for(const q of a){const e=document.querySelector(q);if(e&&e.innerText.trim().length>2)return e.innerText.trim()}return''};const sel=String(getSelection()).trim();const desc=sel.length>200?sel:(J&&J.description?P(J.description):Q('#job-details','.jobs-description__content','.jobs-box__html-content','.description__text','[class*="job-description"]','[class*="JobDescription"]','[class*="jobDescription"]','[data-testid*="description"]','article','main'))||document.body.innerText;const org=J&&J.hiringOrganization?(J.hiringOrganization.name||''):Q('.job-details-jobs-unified-top-card__company-name','.jobs-unified-top-card__company-name','.topcard__org-name-link','[class*="companyName"]','[data-testid*="company"]');const loc=J&&J.jobLocation?[].concat(J.jobLocation).map(l=>l&&l.address&&[l.address.addressLocality,l.address.addressCountry&&(l.address.addressCountry.name||l.address.addressCountry)].filter(Boolean).join(', ')).filter(Boolean).join(' / '):Q('.job-details-jobs-unified-top-card__primary-description-container','.topcard__flavor--bullet','[class*="location"]');const d={url:location.href,title:(J&&J.title)||Q('h1')||document.title,company:org,location:loc.split('\\n')[0].slice(0,120),description:desc.slice(0,20000),page_title:document.title};window.open('${origin}/clip#'+encodeURIComponent(JSON.stringify(d)),'_blank')}catch(e){alert('Could not read this page: '+e.message)}})()`;
  return "javascript:" + encodeURIComponent(js).replace(/'/g, "%27");
}
function bookmarkletSection() {
  return `<section class="card sec" data-part="accounts"><h3>Save jobs from any website</h3>
    <p>Found a job on LinkedIn, Naukri or a company's site? Save it — with its full description — in one click. You're browsing yourself, so no account is ever automated.</p>
    <ol class="howto small"><li>Show your browser's bookmarks bar (⌘⇧B in Chrome).</li><li>Drag this button onto it: <a class="bmk" href="${esc(bookmarkletHref())}" onclick="event.preventDefault();toast('Drag this button to your bookmarks bar')">＋ Save to ${esc((window.BRAND || {}).name || "OfferPilot")}</a></li>
      <li>On any job page, click it. Tip: select the description text first for the cleanest result.</li></ol>
    <p class="small muted">No bookmarks bar? Use “Add a job” on the Jobs page and paste the description.</p></section>`;
}

// ---------------------------------------------------------------- learning plan (Insights)
async function learningCard(gaps) {
  if (!gaps.length) return "";
  const res = await api(`/learning?skills=${encodeURIComponent(gaps.slice(0, 6).join(","))}`).catch(() => []);
  return `<section class="card sec wide learn"><h3>Close your top gaps</h3><p class="small muted" style="margin-top:0">Free, official resources where we know one. If you already have a skill, add it to your profile — but only if you could discuss it in an interview.</p>
    <div class="learngrid">${res.map(x => `<div class="lrow"><b>${esc(x.skill)}</b><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.resource)} ↗</a>
      <button class="btn sm ghost" data-have="${esc(x.skill)}">I have this skill</button></div>`).join("")}</div></section>`;
}
function bindLearning(root) {
  $$("[data-have]", root).forEach(b => b.onclick = async () => {
    const s = b.dataset.have;
    if (!confirm(`Add “${s}” to your profile?\n\nTailoring will then be allowed to mention it, so only add it if you have real experience you could talk about.`)) return;
    try { await api("/profile/skills", { method: "POST", body: { add: [s] } }); S.profile = null; toast(`${s} added — matches updated`); render(); } catch (e) { toast(e.message); }
  });
}

// ---------------------------------------------------------------- interview reminders (desktop notifications)
async function interviewReminders() {
  if (!A11Y.get().notify || !("Notification" in window) || Notification.permission !== "granted") return;
  const ivs = await api("/interviews").catch(() => []);
  for (const iv of ivs) {
    const mins = (new Date(iv.starts_at) - Date.now()) / 60000;
    if (iv.status === "scheduled" && mins > 0 && mins <= 60 && !ls.get("ivn:" + iv.id)) {
      ls.set("ivn:" + iv.id, "1");
      new Notification(`Interview with ${iv.company} in ${Math.round(mins)} min`, { body: iv.link ? "Join link is in OfferPilot › Interviews" : iv.role || "" });
    }
  }
}
