"use strict";
// Verdict, keyword report, resume versions & templates, salary explorer, contacts and LinkedIn review.
// Depends on app.js / toolkit.js / outreach.js globals: $, $$, esc, api, toast, modal, copyText, rel, avatar, I, S, EMPTY, render, go, skillName.

// ---------------------------------------------------------------- "Should I apply?" (job panel)
const CALL = { apply: ["Worth applying", "ok", "✓"], maybe: ["Maybe", "warn", "?"], skip: ["Probably skip", "miss", "✕"] };
function verdictCard(v, breakdown) {
  if (!v) return breakdown ? breakdownCard(breakdown) : "";
  const [label, tone, mark] = CALL[v.call] || CALL.maybe;
  const list = (items, cls, sym) => items.map(x => `<li class="${cls}"><span aria-hidden="true">${sym}</span>${esc(x)}</li>`).join("");
  return `<section class="vcard v-${v.call}" aria-label="Should I apply?">
    <div class="vhead"><span class="vmark" aria-hidden="true">${mark}</span><div><b>${label}</b><div class="small muted">${esc(v.why)}</div></div></div>
    <ul class="vlist">${list(v.blockers || [], "bad", "✕")}${list(v.strengths || [], "good", "✓")}${list(v.cautions || [], "care", "!")}</ul>
    ${breakdown ? `<details class="vmore"><summary>How the match score is made up</summary>${breakdownCard(breakdown)}</details>` : ""}</section>`;
}

// ---------------------------------------------------------------- keyword report (job panel › Match)
function keywordReport(k) {
  if (!k || !k.total) return `<div class="field"><div class="lab">Keyword report</div><p class="small muted" style="margin:0">This posting has too little text to analyse. Get the full description first.</p></div>`;
  const row = (x, have) => `<tr><td><b>${esc(x.term)}</b>${x.must ? ' <span class="chip">required</span>' : ""}</td><td class="num">${x.count || 1}×</td>
    <td>${have ? `<span class="chip ok">✓ ${esc(x.where)}</span>` : `<button class="btn sm" data-addskill="${esc(x.term)}" title="Only if you really have it">I have this — add to skills</button>`}</td></tr>`;
  return `<div class="field"><div class="lab">Keyword report</div>
    <div class="kwbar" role="img" aria-label="Your resume has ${k.have.length} of the ${k.total} keywords in this posting"><i style="width:${Math.round((k.coverage || 0) * 100)}%"></i></div>
    <p class="small muted" style="margin:6px 0 10px">Your resume has <b>${k.have.length} of ${k.total}</b> keywords this posting uses. Applicant-tracking systems look for these words.</p>
    <div class="kwcols">
      <div><h5>Missing (${k.missing.length})</h5>${k.missing.length ? `<table class="kwt"><tbody>${k.missing.slice(0, 14).map(x => row(x, false)).join("")}</tbody></table>` : '<p class="small muted">Nothing missing.</p>'}</div>
      <div><h5>In your resume (${k.have.length})</h5>${k.have.length ? `<table class="kwt"><tbody>${k.have.slice(0, 14).map(x => row(x, true)).join("")}</tbody></table>` : '<p class="small muted">None yet.</p>'}</div>
    </div><div class="hint">Add a missing word only if it is true for you. It then appears in your skills and future resumes; nothing is ever added on its own.</div></div>`;
}
function bindKeywordReport(root, after) {
  $$("[data-addskill]", root).forEach(b => b.onclick = async () => {
    if (!confirm(`Add “${b.dataset.addskill}” to your skills? Only do this if you could discuss it in an interview.`)) return;
    b.disabled = true;
    try { await api("/profile/skills", { method: "POST", body: { add: [b.dataset.addskill] } }); S.profile = await api("/profile"); toast(`${b.dataset.addskill} added — matches are being re-scored`); after && after(); }
    catch (e) { toast(e.message, 5000); b.disabled = false; }
  });
}

// ---------------------------------------------------------------- resume version for one job (job panel › Match)
async function versionPicker(box, r) {
  let v; try { v = await api("/profile/versions"); } catch { return; }
  if (!v.versions.length) return;
  box.innerHTML = `<div class="field"><label class="lab" for="runver">Resume version for this job</label>
    <select class="select" id="runver" style="max-width:320px"><option value="">Active version (${esc((v.versions.find(x => x.id === v.active) || {}).name || "current")})</option>
      ${v.versions.filter(x => x.id !== v.active).map(x => `<option value="${x.id}" ${r.profile_version === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
    <div class="hint">Takes effect the next time you prepare or regenerate this application.</div></div>`;
  $("#runver", box).onchange = async e => { try { await api(`/runs/${r.id}/version`, { method: "PUT", body: { version: e.target.value } }); r.profile_version = e.target.value; toast("Saved — prepare or regenerate to use it"); } catch (x) { toast(x.message); } };
}

// ---------------------------------------------------------------- Settings › Profile: versions and templates
async function profileExtras(box) {
  if (!box) return;
  let v, t; try { [v, t] = await Promise.all([api("/profile/versions"), api("/resume/templates")]); } catch { return; }
  const active = v.versions.find(x => x.id === v.active);
  box.innerHTML = `<div class="proextras">
    <section class="card sec"><h3 style="margin-top:0">Resume versions</h3>
      <p class="small muted" style="margin-top:0">Keep one resume per kind of role, for example “Backend” and “Full-stack”. Each keeps its own job preferences. Switching re-scores your jobs.</p>
      ${v.versions.length ? `<ul class="verlist">${v.versions.map(x => `<li class="${x.id === v.active ? "on" : ""}"><div class="grow"><b>${esc(x.name)}</b>${x.id === v.active ? ' <span class="chip ok">In use</span>' : ""}
          <div class="small muted">${esc(x.headline || "")}${x.skills ? ` · ${x.skills} skills` : ""}${(x.titles || []).length ? ` · looks for ${esc(x.titles.slice(0, 3).join(", "))}` : ""}</div></div>
          ${x.id === v.active ? "" : `<button class="btn sm" data-vuse="${x.id}">Switch to this</button><button class="btn sm ghost danger" data-vdel="${x.id}" aria-label="Delete ${esc(x.name)}">Delete</button>`}</li>`).join("")}</ul>`
        : `<p class="small">No saved versions yet. Save the resume you have now, then upload or edit another and save that too.</p>`}
      <div class="row" style="margin-top:10px"><label class="sr" for="vname">Name for this version</label><input class="input" id="vname" maxlength="40" placeholder="Name the current resume, e.g. Backend" style="flex:1;min-width:180px">
        <button class="btn primary" id="vsave">Save current as a version</button></div>
      ${active ? `<p class="small muted" style="margin-bottom:0">Edits you make are kept in “${esc(active.name)}” when you switch away.</p>` : ""}</section>
    <section class="card sec"><h3 style="margin-top:0">Resume design</h3>
      <p class="small muted" style="margin-top:0">All four are single-column and read correctly by applicant-tracking systems. Your choice is used for every resume and CV from now on.</p>
      <div class="tplrow" role="radiogroup" aria-label="Resume design">${t.templates.map(x => `<button role="radio" aria-checked="${x.id === t.active}" class="tplbtn" data-tpl="${x.id}">${esc(x.label)}</button>`).join("")}</div>
      <div class="tplpreview"><iframe id="tplframe" title="Resume design preview" sandbox=""></iframe></div></section></div>`;
  const show = async id => { try { const r = await fetch(`/api/resume/preview?template=${id}`, { headers: ls.get("token") ? { Authorization: "Bearer " + ls.get("token") } : {} }); $("#tplframe", box).srcdoc = await r.text(); } catch {} };
  show(t.active);
  $$("[data-tpl]", box).forEach(b => b.onclick = async () => {
    $$("[data-tpl]", box).forEach(x => x.setAttribute("aria-checked", String(x === b))); show(b.dataset.tpl);
    try { const s = await api("/settings"); await api("/settings", { method: "PUT", body: { ...s, resume_template: b.dataset.tpl } }); S.settings = null; toast(`${b.textContent} design selected`); } catch (e) { toast(e.message, 5000); }
  });
  $("#vsave", box).onclick = async () => { const n = $("#vname", box).value.trim(); if (!n) return toast("Give it a name first"), $("#vname", box).focus();
    try { await api("/profile/versions", { method: "POST", body: { name: n } }); toast(`Saved as “${n}”`); profileExtras(box); } catch (e) { toast(e.message, 5000); } };
  $$("[data-vuse]", box).forEach(b => b.onclick = async () => { if (!confirm("Switch resume version? Your jobs will be re-scored against it.")) return; b.disabled = true;
    try { const r = await api(`/profile/versions/${b.dataset.vuse}/activate`, { method: "POST" }); S.profile = await api("/profile"); S.settings = null; toast(`Switched — ${r.tailoring} best matches are being prepared`, 5000); render(); } catch (e) { toast(e.message, 5000); b.disabled = false; } });
  $$("[data-vdel]", box).forEach(b => b.onclick = async () => { if (!confirm("Delete this saved version?")) return; try { await api(`/profile/versions/${b.dataset.vdel}`, { method: "DELETE" }); profileExtras(box); } catch (e) { toast(e.message, 5000); } });
}

// ---------------------------------------------------------------- Insights: salary explorer
function salaryCard() {
  return `<section class="card sec wide" id="salarycard"><h3 style="margin-top:0">Salary explorer</h3>
    <p class="small muted" style="margin-top:0">Pay stated in the job listings this app has seen, in ₹ LPA. Filter by role and city.</p>
    <form class="row" id="salform"><label class="sr" for="salrole">Role</label><input class="input" id="salrole" placeholder="Role, e.g. backend engineer" style="flex:1;min-width:200px" value="${esc(S.salRole || "")}">
      <label class="sr" for="salcity">City</label><select class="select" id="salcity" style="width:auto"><option value="">All cities</option></select><button class="btn primary">Show</button></form>
    <div id="salout" style="margin-top:14px"></div></section>`;
}
function bindSalary(root) {
  const card = $("#salarycard", root); if (!card) return;
  const run = async () => {
    const role = $("#salrole", card).value.trim(), city = $("#salcity", card).value; S.salRole = role;
    let d; try { d = await api(`/salary?role=${encodeURIComponent(role)}&city=${encodeURIComponent(city)}`); } catch (e) { $("#salout", card).innerHTML = `<p class="small">${esc(e.message)}</p>`; return; }
    const sel = $("#salcity", card); sel.innerHTML = `<option value="">All cities</option>` + d.cities.map(c => `<option ${c.city === city ? "selected" : ""} value="${esc(c.city)}">${esc(c.city)} (${c.n})</option>`).join("");
    const links = `<div class="row small" style="margin-top:12px"><span class="muted">Compare with:</span>${d.links.map(l => `<a class="btn sm" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.label)} ↗</a>`).join("")}</div>`;
    if (d.median == null) { $("#salout", card).innerHTML = `<p class="small">${d.n ? `Only ${d.n} listing${d.n > 1 ? "s" : ""} state${d.n > 1 ? "" : "s"} pay for this — too few for a range.` : "No listing states pay for this yet."} Try a broader role or all cities.</p>${links}`; return; }
    const pos = x => ((x - d.low) / Math.max(0.1, d.high - d.low)) * 100;
    $("#salout", card).innerHTML = `<div class="salnums"><div><b>₹${d.median} LPA</b><span>typical (median)</span></div><div><b>₹${d.p25}–${d.p75}</b><span>middle half of listings</span></div><div><b>₹${d.low}–${d.high}</b><span>lowest to highest</span></div><div><b>${d.n}</b><span>listings</span></div></div>
      <div class="salbar" role="img" aria-label="Range ₹${d.low} to ₹${d.high} LPA, middle half ₹${d.p25} to ₹${d.p75}, median ₹${d.median}">
        <i class="box" style="left:${pos(d.p25)}%;width:${Math.max(1.5, pos(d.p75) - pos(d.p25))}%"></i><i class="med" style="left:${pos(d.median)}%"></i></div>
      <div class="row small muted" style="justify-content:space-between"><span>₹${d.low} LPA</span><span>₹${d.high} LPA</span></div>
      <div class="kwcols" style="margin-top:14px"><div><h5>By city</h5><table class="kwt"><thead><tr><th>City</th><th class="num">Listings</th><th class="num">Median</th><th class="num">Range</th></tr></thead><tbody>
          ${d.cities.map(c => `<tr><td>${esc(c.city)}</td><td class="num">${c.n}</td><td class="num">₹${c.median}</td><td class="num">₹${c.low}–${c.high}</td></tr>`).join("")}</tbody></table></div>
        <div><h5>Highest in this selection</h5><table class="kwt"><tbody>${d.examples.map(x => `<tr><td><b>${esc(x.title)}</b><div class="small muted">${esc(x.company)} · ${esc(x.city)}</div></td><td class="num">${esc(x.range)}</td></tr>`).join("")}</tbody></table></div></div>
      <p class="small muted" style="margin-bottom:0">${esc(d.note)}</p>${links}`;
  };
  $("#salform", card).onsubmit = e => { e.preventDefault(); run(); };
  $("#salcity", card).onchange = run;
  run();
}

// ---------------------------------------------------------------- Outreach modes: emails / people / LinkedIn profile
const OMODES = [["emails", "Emails"], ["people", "People"], ["linkedin", "LinkedIn profile"]];
const outreachModes = () => `<div class="tabsbar" role="tablist" aria-label="Outreach section">${OMODES.map(([k, l]) => `<button role="tab" aria-selected="${(S.oMode || "emails") === k}" data-om="${k}">${l}</button>`).join("")}</div>`;
function bindOutreachModes(c) { $$("[data-om]", c).forEach(b => b.onclick = () => { S.oMode = b.dataset.om; S.animate = true; render(); }); }

const REL = { recruiter: "Recruiter", referrer: "Referrer", hiring_manager: "Hiring manager", interviewer: "Interviewer", friend: "Friend", other: "Other" };
const REFERRAL = { none: "", asked: "Referral asked", promised: "Referral promised", submitted: "Referral submitted" };
async function vPeople(c) {
  $("#pageactions").innerHTML = `<button class="btn primary" id="pa-person">Add a person</button>`;
  $("#pa-person").onclick = () => contactForm();
  let list; try { list = await api("/contacts"); } catch (e) { c.innerHTML = `<div class="view"><div class="panel empty big"><b>Couldn't load</b><span>${esc(e.message)}</span></div></div>`; return; }
  const due = list.filter(x => x.due);
  const day = s => s ? new Date(s + "T00:00").toLocaleDateString([], { day: "numeric", month: "short" }) : "";
  c.innerHTML = `<div class="view outreach">${outreachModes()}
    <p class="sweeplbl">The people behind each company: who referred you, who you spoke to, and when to get back to them.</p>
    ${due.length ? `<div class="notice"><div class="grow"><b>${due.length} follow-up${due.length > 1 ? "s" : ""} due</b><div class="small muted">${due.slice(0, 4).map(x => esc(x.name)).join(", ")}${due.length > 4 ? " and more" : ""}</div></div></div>` : ""}
    ${list.length ? `<div class="tablewrap"><table class="dt"><thead><tr><th scope="col" class="c-job">Person</th><th scope="col">Company</th><th scope="col">Who they are to you</th><th scope="col">Referral</th>
        <th scope="col">Last spoke</th><th scope="col">Follow up</th><th scope="col" class="c-notes">Notes</th></tr></thead><tbody>
      ${list.map(x => `<tr class="jr" data-person="${x.id}">
        <td class="c-job"><div class="jobcell">${avatar(x.name)}<div class="jt"><button class="rowlink">${esc(x.name)}</button><div class="sub">${esc(x.title || "")}</div></div></div></td>
        <td>${esc(x.company) || '<span class="muted">—</span>'}</td><td>${esc(REL[x.relationship])}</td>
        <td>${REFERRAL[x.referral] ? `<span class="chip ai">${REFERRAL[x.referral]}</span>` : '<span class="muted">—</span>'}</td>
        <td>${x.last_contact ? esc(day(x.last_contact)) : '<span class="muted">—</span>'}</td>
        <td>${x.next_follow_up ? `<span class="chip ${x.due ? "warn" : ""}">${x.due ? "Due now" : esc(day(x.next_follow_up))}</span>` : '<span class="muted">—</span>'}</td>
        <td class="c-notes"><span class="clip1">${esc(x.notes || "")}</span></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="panel empty big">${EMPTY.outreach}<b>Keep track of who you know</b><span>Add recruiters, referrers and interviewers, with notes and a date to follow up.</span><button class="btn primary" id="p-first">Add your first person</button></div>`}</div>`;
  bindOutreachModes(c);
  $$("[data-person]", c).forEach(b => b.onclick = () => contactForm(list.find(x => x.id === b.dataset.person)));
  const f = $("#p-first", c); if (f) f.onclick = () => contactForm();
}
function contactForm(x = {}) {
  const m = modal(x.id ? "Edit person" : "Add a person", `<div class="formgrid">
      <label>Name<input class="input" id="c-name" value="${esc(x.name || "")}" maxlength="120" required></label>
      <label>Company<input class="input" id="c-co" value="${esc(x.company || "")}" maxlength="120"></label>
      <label>Their job title<input class="input" id="c-title" value="${esc(x.title || "")}" maxlength="120"></label>
      <label>Who they are to you<select class="select" id="c-rel">${Object.entries(REL).map(([k, l]) => `<option value="${k}" ${k === (x.relationship || "recruiter") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label>Email<input class="input" id="c-email" type="email" value="${esc(x.email || "")}"></label>
      <label>LinkedIn link<input class="input" id="c-li" value="${esc(x.linkedin_url || "")}" placeholder="https://www.linkedin.com/in/…"></label>
      <label>Referral<select class="select" id="c-ref">${[["none", "No referral"], ["asked", "I asked for one"], ["promised", "They agreed"], ["submitted", "They submitted it"]].map(([k, l]) => `<option value="${k}" ${k === (x.referral || "none") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label>Last spoke on<input class="input" type="date" id="c-last" value="${esc(x.last_contact || "")}"></label>
      <label>Follow up on<input class="input" type="date" id="c-next" value="${esc(x.next_follow_up || "")}"></label>
      <label class="span2">Notes<textarea class="textarea" id="c-notes" style="min-height:110px" maxlength="4000" placeholder="What you talked about, what they suggested, what to send next">${esc(x.notes || "")}</textarea></label></div>
    <div class="row" style="margin-top:14px">${x.id ? `<button class="btn ghost danger" id="c-del">Delete</button>${x.email ? `<button class="btn" id="c-mail">Write them an email</button>` : ""}` : ""}<span class="grow"></span><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="c-save">Save</button></div>`, { wide: true });
  const b = m.body, val = id => $(id, b).value.trim();
  $("#c-save", b).onclick = async e => {
    if (!val("#c-name")) return toast("Add their name"), $("#c-name", b).focus();
    const btn = e.currentTarget; btn.disabled = true;
    const body = { name: val("#c-name"), company: val("#c-co"), title: val("#c-title"), relationship: $("#c-rel", b).value, email: val("#c-email"), linkedin_url: val("#c-li"),
      referral: $("#c-ref", b).value, last_contact: $("#c-last", b).value, next_follow_up: $("#c-next", b).value, notes: $("#c-notes", b).value };
    try { await api(x.id ? `/contacts/${x.id}` : "/contacts", { method: x.id ? "PUT" : "POST", body }); m.close(); toast("Saved"); S.oMode = "people"; S.view === "outreach" ? render() : go("outreach"); }
    catch (err) { toast(err.message, 5000); btn.disabled = false; }
  };
  const del = $("#c-del", b); if (del) del.onclick = async () => { if (!confirm("Delete this person?")) return; await api(`/contacts/${x.id}`, { method: "DELETE" }); m.close(); render(); };
  const mail = $("#c-mail", b); if (mail) mail.onclick = async () => { mail.disabled = true;
    try { const o = await api("/outreach", { method: "POST", body: { contact_name: x.name, contact_title: x.title, email: x.email, company: x.company || x.name, linkedin_url: x.linkedin_url } });
      m.close(); S.oMode = "emails"; S.otab = "draft"; render(); setTimeout(() => outreachModal(o), 350); } catch (err) { toast(err.message, 6000); mail.disabled = false; } };
  $("#c-name", b).focus();
}

async function vLinkedIn(c) {
  $("#pageactions").innerHTML = "";
  const d = S.liDraft || (S.liDraft = { headline: "", about: "", skills: "" });
  c.innerHTML = `<div class="view outreach">${outreachModes()}
    <p class="sweeplbl">Recruiters find people through LinkedIn search. Paste your profile text to get a score and rewrites built from your resume. Nothing is sent to LinkedIn, and the app never opens your profile.</p>
    <div class="ligrid"><section class="card sec"><h3 style="margin-top:0">Your LinkedIn profile now</h3>
        <label class="lab" for="li-h">Headline</label><input class="input" id="li-h" maxlength="400" value="${esc(d.headline)}" placeholder="The line under your name">
        <label class="lab" for="li-a" style="margin-top:10px;display:block">About</label><textarea class="textarea" id="li-a" style="min-height:170px" placeholder="Paste your About section">${esc(d.about)}</textarea>
        <label class="lab" for="li-s" style="margin-top:10px;display:block">Skills (comma separated)</label><textarea class="textarea" id="li-s" style="min-height:70px" placeholder="Python, AWS, …">${esc(d.skills)}</textarea>
        <div class="row" style="margin-top:12px"><a class="btn" href="https://www.linkedin.com/in/me/" target="_blank" rel="noopener noreferrer">${I.ext}Open my LinkedIn</a><span class="grow"></span><button class="btn primary" id="li-go">Review my profile</button></div></section>
      <section class="card sec" id="li-out"><div class="empty">${EMPTY.search}<b>Your review appears here</b></div></section></div></div>`;
  bindOutreachModes(c);
  $("#li-go", c).onclick = async e => {
    const btn = e.currentTarget; Object.assign(d, { headline: $("#li-h", c).value, about: $("#li-a", c).value, skills: $("#li-s", c).value });
    btn.disabled = true;
    try {
      const r = await api("/linkedin/review", { method: "POST", body: d });
      const areas = ["Headline", "About", "Skills"];
      $("#li-out", c).innerHTML = `<div class="row" style="flex-wrap:nowrap;margin-bottom:10px">${ringSvg(r.score / 100, String(r.score), 72)}<div><h3 style="margin:0">${esc(r.grade)}</h3><span class="small muted">out of 100</span></div></div>
        ${areas.map(a => `<h5>${a}</h5><ul class="vlist">${r.checks.filter(x => x.area === a).map(x => `<li class="${x.ok ? "good" : "care"}"><span aria-hidden="true">${x.ok ? "✓" : "!"}</span>${esc(x.text)}</li>`).join("")}</ul>`).join("")}
        ${r.add_skills.length ? `<h5>Add these skills on LinkedIn</h5><div class="row" style="gap:6px">${r.add_skills.map(s => `<span class="chip ok">${esc(s)}</span>`).join("")}</div>` : ""}
        <h5>Suggested headline</h5><div class="lisug"><p id="li-nh">${esc(r.headline)}</p><button class="btn sm" data-copy="li-nh">Copy</button></div>
        <h5>Suggested About</h5><div class="lisug"><p id="li-na" style="white-space:pre-wrap">${esc(r.about)}</p><button class="btn sm" data-copy="li-na">Copy</button></div>
        <p class="small muted" style="margin-bottom:0">${esc(r.note)}</p>`;
      $$("[data-copy]", c).forEach(x => x.onclick = async () => { await copyText($("#" + x.dataset.copy, c).innerText); toast("Copied — paste it into LinkedIn"); });
    } catch (err) { toast(err.message, 5000); }
    btn.disabled = false;
  };
}

// ---------------------------------------------------------------- Settings: browser extension instructions
function extensionSection() {
  return `<section class="card sec" data-part="accounts"><h3 style="margin-top:0">Fill application forms in one click</h3>
    <p>The ${esc((window.BRAND || {}).name || "OfferPilot")} browser extension fills your name, email, phone, location, LinkedIn and (if you pick an application) your cover letter on company application pages such as Greenhouse, Lever, Ashby and Workday. You check it and press Submit yourself.</p>
    <ol class="howto small"><li>Open <code>chrome://extensions</code> in Chrome, Edge or Brave and switch on <b>Developer mode</b>.</li>
      <li>Click <b>Load unpacked</b> and choose the <code>extension</code> folder inside this app's folder.</li>
      <li>On an application page, click the extension's icon, then <b>Fill this form</b>.</li></ol>
    <p class="small muted" style="margin-bottom:0">It never presses Submit, never uploads files, and leaves salary, visa, demographic and consent questions for you. It only works while this app is running on your computer.</p></section>`;
}
