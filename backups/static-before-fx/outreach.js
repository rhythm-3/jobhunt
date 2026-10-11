"use strict";
// Outreach: personalised email + tailored CV to people at companies, approval-gated, with a tracker.
// Depends on app.js / toolkit.js globals: $, $$, esc, api, toast, modal, download, copyText, rel, avatar, ago, I, S, EMPTY, celebrate, render.

const OSTATUS = {
  draft: ["To review", "warn"], approved: ["Approved", "info"], sent: ["Sent", ""], replied: ["Replied", "ok"], interview: ["Interview", "ok"],
  declined: ["Declined", ""], bounced: ["Bounced", "warn"], do_not_contact: ["Do not contact", ""],
};
const OTABS = [
  ["all", "All", () => true], ["draft", "To review", o => o.status === "draft"], ["approved", "Approved", o => o.status === "approved"],
  ["sent", "Waiting for reply", o => o.status === "sent"], ["due", "Follow-up due", o => o.follow_up_due],
  ["replied", "Replied", o => ["replied", "interview"].includes(o.status)], ["closed", "Closed", o => ["declined", "bounced", "do_not_contact"].includes(o.status)],
];
let OUT = { items: [], stats: {}, queue: {}, dry_run: true, gmail: false };
let outPoll = null, prevRunning = false;

const liSearch = (co, what) => `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(`${co} ${what}`)}`;
const ostatusChip = o => {
  const [l, tone] = OSTATUS[o.status] || [o.status, ""];
  return `<span class="chip ${tone}">${esc(o.practice && o.status === "sent" ? "Sent (practice)" : l)}</span>`;
};
const owhen = o => o.status === "sent" || o.sent_at
  ? `${o.practice ? "Practice send " : "Sent "}${esc(ago(o.sent_at))}${o.follow_up_due ? '<div class="sub dueflag">Follow-up due</div>' : o.stale ? '<div class="sub">No reply yet</div>' : ""}`
  : `Added ${esc(ago(o.created_at))}`;

async function vOutreach(c) {
  if (S.oMode === "people") return vPeople(c);
  if (S.oMode === "linkedin") return vLinkedIn(c);
  $("#pageactions").innerHTML = `<button class="btn" id="pa-auto" title="Prepare a draft for each of your best new matches">Draft from my best matches</button><button class="btn" id="pa-import">Paste several</button><button class="btn primary" id="pa-add">Add a contact</button>`;
  $("#pa-add").onclick = () => outreachForm(); $("#pa-import").onclick = () => outreachImport();
  $("#pa-auto").onclick = async e => { const b = e.currentTarget; b.disabled = true; try { const r = await api("/outreach/auto-draft", { method: "POST", body: {} });
    toast(r.created ? `${r.created} draft${r.created > 1 ? "s" : ""} prepared — add who to write to` : "No new matches to draft for right now"); S.otab = "draft"; render(); } catch (x) { toast(x.message, 5000); b.disabled = false; } };
  try { OUT = await api("/outreach"); } catch (e) { c.innerHTML = `<div class="view"><div class="card empty big"><b>Couldn't load</b><span>${esc(e.message)}</span></div></div>`; return; }
  const { items, stats: st, queue } = OUT;
  if (prevRunning && !queue.running && S.otab === "approved") S.otab = "sent";     // a send run just finished: show where they went
  prevRunning = !!queue.running;
  S.otab = OTABS.some(t => t[0] === S.otab) ? S.otab : "all";
  const tab = OTABS.find(t => t[0] === S.otab), shown = items.filter(tab[2]);
  const counts = Object.fromEntries(OTABS.map(t => [t[0], items.filter(t[2]).length]));
  const ready = items.filter(o => o.status === "draft" && o.reviewed && !(o.blockers || []).length);
  const capPct = Math.min(100, Math.round((st.sent_today / st.cap) * 100));
  c.innerHTML = `<div class="view outreach">${outreachModes()}
    <div class="kpis" role="list" aria-label="Outreach at a glance">
      ${[["To review", st.drafts, "draft"], ["Approved", st.approved, "approved"], ["Sent", st.sent, "sent"], ["Replied", st.replied, "replied"], ["Interviews", st.interviews, "replied"]].map(([l, n, k]) =>
        `<button class="kpi" role="listitem" data-ostage="${k}"><span class="kl">${l}</span><b data-count="${n || 0}">${n || 0}</b></button>`).join("")}
      <div class="kpi" role="listitem"><span class="kl">Reply rate</span><b>${st.reply_rate == null ? "–" : Math.round(st.reply_rate * 100) + "%"}</b><small>${st.reply_rate == null ? "after your first real send" : "of emails really sent"}</small></div>
      <div class="kpi" role="listitem"><span class="kl">Sent in 24 hours</span><b>${st.sent_today}<span class="of"> of ${st.cap}</span></b>
        <span class="capbar" role="img" aria-label="${capPct}% of the daily limit used"><i style="width:${capPct}%"></i></span></div>
    </div>
    ${st.approved ? `<div class="notice sendbar"><div class="grow"><b>${st.approved} approved email${st.approved > 1 ? "s" : ""} ready to send</b>
        <div class="small muted">${queue.running ? `Sending: ${queue.sent} of ${queue.total} done. They go out about a minute apart.` : queue.note ? esc(queue.note) : `They go out one at a time, about a minute apart, within your daily limit${OUT.dry_run ? ". Practice mode: nothing is really sent" : ""}.`}</div></div>
        <button class="btn primary" id="osendall" ${queue.running ? "disabled" : ""}>${I.send}${queue.running ? "Sending…" : "Send all approved"}</button></div>` : ""}
    ${ready.length ? `<div class="notice sendbar"><div class="grow"><b>${ready.length} reviewed draft${ready.length > 1 ? "s" : ""} ready</b>
        <div class="small muted">You've read ${ready.length > 1 ? "them" : "it"} and every check passes. One click approves and sends ${ready.length > 1 ? "them" : "it"}.</div></div>
        <button class="btn primary" id="oready">${I.send}Approve and send ${ready.length}</button></div>` : ""}
    <div class="toolbar"><div class="seg" role="group" aria-label="Show">${OTABS.filter(t => counts[t[0]] || ["all", "draft", "sent"].includes(t[0]) || t[0] === S.otab).map(([k, l]) =>
        `<button aria-pressed="${k === S.otab}" data-ot="${k}">${l} <span class="muted">${counts[k]}</span></button>`).join("")}</div>
      <span class="grow"></span>${st.follow_ups_due ? `<span class="chip warn">${st.follow_ups_due} follow-up${st.follow_ups_due === 1 ? "" : "s"} due</span>` : ""}
      ${OUT.gmail ? `<button class="btn" id="ocheck">Check for replies</button>` : ""}</div>
    ${shown.length ? `<div class="tablewrap"><table class="dt"><thead><tr><th scope="col" class="c-job">Person</th><th scope="col">Company and role</th><th scope="col" class="c-via">Through</th><th scope="col" class="c-stage">Status</th>
        <th scope="col">Activity</th><th class="c-act"><span class="sr">Action</span></th></tr></thead><tbody>${shown.map(otr).join("")}</tbody></table></div>` : oempty(items.length)}
    <p class="small muted osafe">Only email people whose contact details are public for hiring: their LinkedIn profile, a careers page or a job post. Every email says who you are, attaches your CV, includes an opt-out line, and is sent only after you approve it.</p>
  </div>`;
  bindOutreachModes(c);
  $$("[data-ot]", c).forEach(b => b.onclick = () => { S.otab = b.dataset.ot; vOutreach(c); });
  $$("[data-ostage]", c).forEach(b => b.onclick = () => { S.otab = b.dataset.ostage; vOutreach(c); });
  $$("[data-oopen]", c).forEach(b => b.onclick = e => { if (e.target.closest("[data-oquick],a")) return; outreachModal(items.find(o => o.id === b.dataset.oopen)); });
  $$("[data-oquick]", c).forEach(b => b.onclick = e => { e.stopPropagation(); quickAction(b.dataset.oquick, items.find(o => o.id === b.dataset.oid), b); });
  const nb = $("#oadd", c); if (nb) nb.onclick = () => outreachForm();
  const ck = $("#ocheck", c); if (ck) ck.onclick = async () => { ck.disabled = true; try { const r = await api("/outreach/check-replies", { method: "POST" }); toast(r.updated ? `${r.updated} update${r.updated > 1 ? "s" : ""} found` : "No new replies"); vOutreach(c); } catch (e) { toast(e.message, 5000); ck.disabled = false; } };
  const rd = $("#oready", c); if (rd) rd.onclick = () => approveSendDialog(ready);
  const sa = $("#osendall", c); if (sa) sa.onclick = async () => { sa.disabled = true; try { await api("/outreach/send-approved", { method: "POST" }); prevRunning = true; toast("Sending started — they go out one at a time"); } catch (e) { toast(e.message, 5000); } vOutreach(c); };
  countUp(c);
  clearTimeout(outPoll);                                   // poll only while a send run is in progress
  if (queue.running) outPoll = setTimeout(() => { if (S.view === "outreach" && !$(".tk-modal")) vOutreach(c); else if (S.view === "outreach") outPoll = setTimeout(() => vOutreach(c), 4000); }, 4000);
}

function oempty(total) {
  return total ? `<div class="panel empty big">${EMPTY.cards}<b>Nothing in this list</b></div>`
    : `<div class="panel empty big">${EMPTY.outreach}<b>Reach the people who hire</b>
        <span>Find a recruiter or hiring manager on LinkedIn, add them here, and get a personal email with your CV ready to approve.</span>
        <button class="btn primary" id="oadd">Add your first contact</button></div>`;
}

function otr(o) {
  const quick = o.needs_contact ? `<a class="btn sm" href="${esc(liSearch(o.company, "talent acquisition recruiter"))}" target="_blank" rel="noopener noreferrer">Find the person</a>`
    : o.status === "draft" ? `<button class="btn sm" data-oquick="review" data-oid="${o.id}">${o.reviewed ? "Review" : "Read"} and approve</button>`
    : o.status === "approved" ? `<button class="btn sm" data-oquick="unapprove" data-oid="${o.id}">Take back</button>`
    : o.follow_up_due ? `<button class="btn sm" data-oquick="followup" data-oid="${o.id}">Follow up</button>`
    : o.status === "sent" ? `<button class="btn sm ghost" data-oquick="replied" data-oid="${o.id}">They replied</button>` : `<button class="btn sm ghost">Open</button>`;
  const who = o.needs_contact ? "Who to write to?" : (o.contact_name || o.email || "Contact");
  return `<tr class="jr${o.needs_contact ? " todo" : ""}" data-oopen="${o.id}">
    <td class="c-job"><div class="jobcell">${avatar(o.needs_contact ? "?" : who)}<div class="jt"><button class="rowlink">${esc(who)}</button><div class="sub">${esc(o.contact_title || (o.needs_contact ? "No contact added yet" : o.email || ""))}</div></div></div></td>
    <td><b class="cellmain">${esc(o.company)}</b><div class="sub">${esc(o.role || "")}</div>${o.reply_snippet ? `<div class="oreply">“${esc(o.reply_snippet)}”</div>` : ""}</td>
    <td class="c-via">${o.needs_contact ? '<span class="muted">Not set</span>' : o.channel === "email" ? "Email" + (o.attach ? ", CV attached" : "") : "LinkedIn message"}</td>
    <td class="c-stage">${ostatusChip(o)}</td>
    <td>${owhen(o)}</td>
    <td class="c-act">${quick}</td></tr>`;
}
async function quickAction(kind, o, btn) {
  btn.disabled = true;
  try {
    if (kind === "review") return outreachModal(o);
    if (kind === "followup") return outreachModal(o, "followup");
    if (kind === "unapprove") await api(`/outreach/${o.id}/unapprove`, { method: "POST" });
    if (kind === "replied") await api(`/outreach/${o.id}/mark`, { method: "POST", body: { status: "replied" } });
    render();
  } catch (e) { toast(e.message, 5000); btn.disabled = false; }
}

// ---------------------------------------------------------------- add one contact
function outreachForm() {
  const runs = (S.runs || []).filter(r => !["filtered"].includes(r.status)).sort((a, b) => (b.match_score || 0) - (a.match_score || 0)).slice(0, 80);
  const m = modal("Add a contact", `
    <p class="small muted" style="margin-top:0">Find a recruiter or hiring manager yourself, then add what's public. We never scrape LinkedIn or guess email addresses.</p>
    <div class="formgrid">
      <label class="span2">For a job you saved (optional — fills the company, role and posting)<select class="select" id="orun"><option value="">— none —</option>${runs.map(r => `<option value="${esc(r.id)}">${esc(r.job.company)} — ${esc(r.job.title)}</option>`).join("")}</select></label>
      <label>Company<input class="input" id="oco" required maxlength="120"></label>
      <label>Role (optional)<input class="input" id="orole" maxlength="200" placeholder="e.g. Detection Engineer"></label>
      <div class="span2 row" id="olinks"><button class="btn sm" type="button" id="ofind">${I.search}Find HR or recruiters on LinkedIn</button><span class="small muted">Opens LinkedIn in your own browser.</span></div>
      <label>Their name<input class="input" id="oname" maxlength="120" placeholder="e.g. Priya Sharma"></label>
      <label>Their job title<input class="input" id="otitle" maxlength="120" placeholder="e.g. Talent Acquisition"></label>
      <label>Email address<input class="input" id="oemail" type="email" maxlength="200" placeholder="only if it's public, e.g. on a job post"></label>
      <label>LinkedIn profile link<input class="input" id="oli" placeholder="https://www.linkedin.com/in/…"></label>
      <label class="span2">Why this company? One sentence in your own words (makes replies far more likely)<input class="input" id="onote" maxlength="600" placeholder="e.g. I've followed your detection-as-code work and it's the kind of problem I enjoy."></label>
      <label class="span2">Job posting (optional — paste it so the email and CV match the role)<textarea class="textarea" id="ojd" style="min-height:110px"></textarea></label>
    </div>
    <div class="row" style="margin-top:14px"><span class="grow"></span><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="osave">Create draft</button></div>`, { wide: true });
  const b = m.body;
  $("#orun", b).onchange = e => { const r = S.runs.find(x => x.id === e.target.value); if (r) { $("#oco", b).value = r.job.company; $("#orole", b).value = r.job.title; } };
  $("#ofind", b).onclick = async () => {
    const co = $("#oco", b).value.trim(); if (!co) return toast("Type the company first"), $("#oco", b).focus();
    try {
      const l = await api(`/outreach/links?company=${encodeURIComponent(co)}&role=${encodeURIComponent($("#orole", b).value.trim())}`);
      $("#olinks", b).innerHTML = `<span class="small muted">Open in your browser:</span>
        <a class="btn sm" href="${esc(l.linkedin_recruiters)}" target="_blank" rel="noopener noreferrer">Recruiters at ${esc(co)} ↗</a>
        <a class="btn sm" href="${esc(l.linkedin_managers)}" target="_blank" rel="noopener noreferrer">Hiring managers ↗</a>
        <a class="btn sm" href="${esc(l.careers_contact)}" target="_blank" rel="noopener noreferrer">Careers contact page ↗</a>`;
    } catch (e) { toast(e.message); }
  };
  $("#osave", b).onclick = async e => {
    const btn = e.currentTarget, body = { run_id: $("#orun", b).value || null, company: $("#oco", b).value.trim(), role: $("#orole", b).value.trim(), contact_name: $("#oname", b).value.trim(),
      contact_title: $("#otitle", b).value.trim(), email: $("#oemail", b).value.trim(), linkedin_url: $("#oli", b).value.trim(), note: $("#onote", b).value.trim(), job_text: $("#ojd", b).value.trim() };
    if (!body.company && !body.run_id) return toast("Add the company"), $("#oco", b).focus();
    btn.disabled = true;
    try { const o = await api("/outreach", { method: "POST", body }); m.close(); S.otab = "draft"; if (S.view !== "outreach") go("outreach"); else render();
      setTimeout(() => outreachModal(o), 350); }
    catch (x) { toast(x.message, 6000); btn.disabled = false; }
  };
  $("#oco", b).focus();
}

function outreachImport() {
  const m = modal("Paste several contacts", `
    <p class="small muted" style="margin-top:0">One person per line: <b>Name, email, Company, Role</b> (role is optional). Use a LinkedIn link instead of an email if that's all you have. Up to 50 lines. A draft is written for each — nothing is sent until you approve it.</p>
    <textarea class="textarea" id="oimp" style="min-height:180px" placeholder="Priya Sharma, priya@acme.com, Acme, Detection Engineer&#10;Sam Lee, https://www.linkedin.com/in/samlee, Initech"></textarea>
    <div class="row" style="margin-top:12px"><span class="grow"></span><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="oimpgo">Create drafts</button></div><div id="oimpout"></div>`);
  $("#oimpgo", m.body).onclick = async e => {
    const btn = e.currentTarget; btn.disabled = true;
    try {
      const r = await api("/outreach/import", { method: "POST", body: { text: $("#oimp", m.body).value } });
      if (!r.skipped.length) { m.close(); toast(`${r.created} draft${r.created === 1 ? "" : "s"} created`); S.otab = "draft"; return render(); }
      $("#oimpout", m.body).innerHTML = `<div class="warnbox" style="margin-top:12px"><b>${r.created} created, ${r.skipped.length} skipped</b><ul class="small">${r.skipped.map(s => `<li>${esc(s.line)} — ${esc(s.reason)}</li>`).join("")}</ul></div>`;
      btn.disabled = false; if (r.created) { S.otab = "draft"; render(); }
    } catch (x) { toast(x.message, 5000); btn.disabled = false; }
  };
  $("#oimp", m.body).focus();
}

// ---------------------------------------------------------------- review / tracker dialog
function outreachModal(o0, focus) {
  let o = o0;
  const editable = () => ["draft", "approved"].includes(o.status);
  const m = modal(`${o.contact_name || o.email || "New contact"} · ${o.company}`, `<div id="obody"></div>`, { wide: true });
  if (["draft", "approved"].includes(o.status) && !o.reviewed) api(`/outreach/${o.id}/reviewed`, { method: "POST" }).then(r => { o = { ...o, reviewed: r.reviewed }; render(); }).catch(() => {});   // opening it counts as reading it
  const words = t => t.trim().split(/\s+/).filter(Boolean).length;
  const draw = () => {
    const b = $("#obody", m.el);
    const evs = (o.events || []).slice().reverse();
    b.innerHTML = `
      <div class="row" style="margin-bottom:10px">${ostatusChip(o)}<span class="small muted">${owhen(o)}</span><span class="grow"></span>
        ${o.linkedin_url ? `<a class="btn sm" href="${esc(o.linkedin_url)}" target="_blank" rel="noopener noreferrer">Their LinkedIn ↗</a>` : ""}</div>
      ${o.reply_snippet ? `<div class="okbox" style="margin-top:0"><b>Their reply:</b> “${esc(o.reply_snippet)}”</div>` : ""}
      ${(o.blockers || []).length ? `<div class="warnbox" style="margin-top:0"><b>Before this can go out</b><ul class="small" style="margin:6px 0 0 18px;padding:0">${o.blockers.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
      ${editable() ? `<div class="row" style="margin-bottom:10px"><span class="small muted">Find the person (opens LinkedIn in your browser):</span>
        <a class="btn sm" href="${esc(liSearch(o.company, "talent acquisition recruiter"))}" target="_blank" rel="noopener noreferrer">Recruiters ↗</a>
        <a class="btn sm" href="${esc(liSearch(o.company, o.role || "hiring manager"))}" target="_blank" rel="noopener noreferrer">Hiring managers ↗</a></div>` : ""}
      <div class="formgrid" ${editable() ? "" : 'style="opacity:.92"'}>
        ${editable() ? `<label>Their name<input class="input" id="m-name" value="${esc(o.contact_name)}" maxlength="120" placeholder="e.g. Priya Sharma"></label>
        <label>Their job title<input class="input" id="m-title" value="${esc(o.contact_title)}" maxlength="120" placeholder="e.g. Talent Acquisition"></label>
        <label class="span2">LinkedIn profile link<input class="input" id="m-li" value="${esc(o.linkedin_url)}" placeholder="https://www.linkedin.com/in/…"></label>` : ""}
        <label>To (email)<input class="input" id="m-email" value="${esc(o.email)}" ${editable() ? "" : "disabled"} placeholder="add it, or copy the message to LinkedIn"></label>
        <label>Subject<input class="input" id="m-subject" value="${esc(o.subject)}" ${editable() ? "" : "disabled"}></label>
        <label class="span2">Message <span class="muted small" id="m-wc">${words(o.body)} words</span><textarea class="textarea" id="m-body" style="min-height:250px" ${editable() ? "" : "disabled"}>${esc(o.body)}</textarea></label>
        ${editable() ? `<label class="span2">Your own sentence on why this company<input class="input" id="m-note" maxlength="600" value="${esc(o.note)}" placeholder="Then press “Rewrite” to work it into the email"></label>
          <details class="span2"><summary class="small">Job posting used to tailor the email and CV</summary><textarea class="textarea" id="m-jd" style="min-height:120px;margin-top:8px" placeholder="Paste the job description here, then press “Rewrite”">${esc(o.job_text)}</textarea></details>
          <div class="span2 row"><label class="row" style="font-weight:400;display:flex"><input type="checkbox" id="m-attach" ${o.attach ? "checked" : ""}> Attach my CV, tailored to this role</label>
            <button class="btn sm" type="button" id="m-cv">Preview the CV</button></div>` : ""}
      </div>
      ${editable() ? `<div class="row" style="margin-top:12px"><button class="btn sm" id="m-rewrite" title="Write the email again from your note and the posting">Rewrite</button>
          <button class="btn sm" id="m-polish" title="Smooth the wording with the AI; it can't add facts">Polish with AI</button>
          <button class="btn sm" id="m-copy">Copy message</button>${o.channel === "linkedin" || !o.email ? `<button class="btn sm" id="m-sent">I sent it on LinkedIn</button>` : ""}
          <span class="grow"></span><button class="btn sm ghost danger" id="m-del">Delete</button><button class="btn" id="m-save">Save</button>
          ${o.status === "draft" ? `<button class="btn primary" id="m-approve">Approve</button>` : `<button class="btn" id="m-unapprove">Take back approval</button>`}
          <button class="btn primary" id="m-send">${I.send}Send now</button></div>
        <p class="small muted" style="margin-bottom:0">${o.status === "draft" ? "Approve queues it for “Send all approved” (sent one by one, about a minute apart). “Send now” sends just this one." : "Approved: it goes out with “Send all approved”, or send it right now."} ${OUT.dry_run ? "<b>Practice mode — nothing is really sent.</b>" : ""}</p>` : `
        ${o.status === "sent" ? followupPanel() : ""}
        <div class="row" style="margin-top:12px"><button class="btn sm" id="m-cv">Download the CV that was sent</button><button class="btn sm" id="m-copy">Copy message</button><span class="grow"></span>
          ${["sent", "replied", "interview"].includes(o.status) ? `<span class="small muted">Update:</span>
          ${o.status !== "replied" ? `<button class="btn sm" data-mark="replied">They replied</button>` : ""}<button class="btn sm" data-mark="interview">Interview</button><button class="btn sm" data-mark="declined">Declined</button>` : ""}
          <button class="btn sm ghost danger" data-mark="do_not_contact" title="Never email them again">Do not contact</button>${o.status !== "do_not_contact" ? `<button class="btn sm ghost danger" id="m-del">Delete</button>` : ""}</div>`}
      <h4 style="margin:18px 0 6px">History</h4>
      <ol class="otl">${evs.map(e => `<li><span class="small muted">${esc(rel(e.at))}</span> <b>${esc(e.event.replace(/_/g, " "))}</b>${e.detail ? ` — <span class="muted">${esc(e.detail)}</span>` : ""}</li>`).join("") || '<li class="muted">No activity yet.</li>'}</ol>`;
    bind(b);
  };
  const followupPanel = () => {
    const due = o.follow_up_due, done = o.followups_sent >= 1;
    return `<div class="card sec" style="margin-top:12px" id="m-fu"><h4 style="margin:0 0 6px">Follow-up ${done ? "(sent)" : due ? '<span class="chip warn">due</span>' : ""}</h4>
      ${done ? `<p class="small muted" style="margin:0">You followed up ${esc(rel(o.last_followup_at))}. One follow-up is the polite limit.</p>`
        : `<p class="small muted" style="margin-top:0">${due ? "It's been a few days. One short, friendly nudge is fine." : "Available about 5 days after the first email."}</p>
          ${o.followup_body ? `<textarea class="textarea" id="fu-body" style="min-height:130px">${esc(o.followup_body)}</textarea>` : ""}
          <div class="row" style="margin-top:8px"><button class="btn sm" id="fu-draft">${o.followup_body ? "Write it again" : "Write a follow-up"}</button>
            ${o.followup_body ? `<button class="btn sm" id="fu-save">Save</button><button class="btn sm primary" id="fu-send" ${o.email ? "" : "disabled"}>${I.send}Send follow-up</button>` : ""}</div>`}</div>`;
  };
  const collect = b => ({ contact_name: $("#m-name", b).value.trim(), contact_title: $("#m-title", b).value.trim(), linkedin_url: $("#m-li", b).value.trim(), email: $("#m-email", b).value.trim(), subject: $("#m-subject", b).value, body: $("#m-body", b).value,
    note: $("#m-note", b).value.trim(), job_text: $("#m-jd", b).value, attach: $("#m-attach", b).checked });
  const set = x => { o = { ...o, ...x }; draw(); render(); };   // also refreshes the list behind the dialog
  const act = async (btn, fn) => { if (btn) btn.disabled = true; try { await fn(); } catch (e) { toast(e.message, 6000); } finally { if (btn && btn.isConnected) btn.disabled = false; } };
  const bind = b => {
    const ta = $("#m-body", b); if (ta) ta.oninput = () => { $("#m-wc", b).textContent = `${words(ta.value)} words`; };
    const on = (id, fn) => { const el = $(id, b); if (el) el.onclick = () => act(el, fn); };
    on("#m-save", async () => { set(await api(`/outreach/${o.id}`, { method: "PUT", body: collect(b) })); toast("Saved"); });
    on("#m-rewrite", async () => { const c = collect(b); await api(`/outreach/${o.id}`, { method: "PUT", body: c }); const r = await api(`/outreach/${o.id}/draft`, { method: "POST", body: { note: c.note, job_text: c.job_text, contact_name: c.contact_name } }); set(r); toast(r.warnings && r.warnings[0] ? r.warnings[0] : "Email rewritten", 5000); });
    on("#m-polish", async () => { const c = collect(b); await api(`/outreach/${o.id}`, { method: "PUT", body: c }); const r = await api(`/outreach/${o.id}/draft`, { method: "POST", body: { note: c.note, job_text: c.job_text, contact_name: c.contact_name, polish: true } }); set(r);
      toast(r.method === "template" ? (r.warnings.find(w => /polish/i.test(w)) || "The AI isn't available, so the plain version is kept.") : "Polished — read it once before approving", 6000); });
    on("#m-approve", async () => { await api(`/outreach/${o.id}`, { method: "PUT", body: collect(b) }); S.otab = "approved"; set(await api(`/outreach/${o.id}/approve`, { method: "POST" })); toast("Approved — it goes out with “Send all approved”"); });
    on("#m-unapprove", async () => set(await api(`/outreach/${o.id}/unapprove`, { method: "POST" })));
    on("#m-send", async () => { await api(`/outreach/${o.id}`, { method: "PUT", body: collect(b) }); const r = await api(`/outreach/${o.id}/send`, { method: "POST" });
      S.otab = "sent"; set(r); celebrate(r.dry_run ? "Sent (practice mode — not really sent)" : "Email sent with your CV"); });
    on("#m-sent", async () => { set(await api(`/outreach/${o.id}/contacted`, { method: "POST" })); toast("Tracking it — you'll see when a follow-up is due"); });
    on("#m-cv", async () => { await download(`/outreach/${o.id}/cv`, "CV.pdf"); toast("CV downloaded"); });
    on("#m-copy", async () => { await copyText(`${$("#m-subject", b) ? $("#m-subject", b).value : o.subject}\n\n${$("#m-body", b) ? $("#m-body", b).value : o.body}`); toast("Copied — paste it into LinkedIn or your mail app"); });
    on("#m-del", async () => { if (!confirm("Delete this contact?")) return; await api(`/outreach/${o.id}`, { method: "DELETE" }); m.close(); render(); });
    on("#fu-draft", async () => set(await api(`/outreach/${o.id}/followup/draft`, { method: "POST" })));
    on("#fu-save", async () => set(await api(`/outreach/${o.id}`, { method: "PUT", body: { followup_body: $("#fu-body", b).value } })));
    on("#fu-send", async () => { await api(`/outreach/${o.id}`, { method: "PUT", body: { followup_body: $("#fu-body", b).value } }); const r = await api(`/outreach/${o.id}/followup/send`, { method: "POST" });
      set(r); toast(r.dry_run ? "Follow-up recorded (practice mode)" : "Follow-up sent"); });
    $$("[data-mark]", b).forEach(x => x.onclick = () => act(x, async () => {
      if (x.dataset.mark === "do_not_contact" && !confirm("Mark as do not contact? You'll never be able to email them from here.")) return;
      set(await api(`/outreach/${o.id}/mark`, { method: "POST", body: { status: x.dataset.mark } })); }));
  };
  draw();
  if (focus === "followup") setTimeout(() => { const f = $("#m-fu", m.el); if (f) f.scrollIntoView({ block: "center" }); const d = $("#fu-draft", m.el); if (d && !o.followup_body) d.click(); }, 60);
}

function approveSendDialog(list) {
  const m = modal(`Approve & send ${list.length} email${list.length > 1 ? "s" : ""}`, `
    <p style="margin-top:0">You've read these and every check passes. Each one goes out with your CV attached, one at a time about a minute apart, within your daily limit${OUT.dry_run ? " — <b>practice mode: nothing is really sent</b>" : ""}.</p>
    <ul class="plain">${list.map(o => `<li><b>${esc(o.contact_name || o.email)}</b> · ${esc(o.company)}<div class="small muted">${esc(o.subject)}${o.email ? ` → ${esc(o.email)}` : ""}</div></li>`).join("")}</ul>
    <div class="row" style="margin-top:14px"><span class="grow"></span><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="oconfirm">${I.send}Send ${list.length}</button></div>`);
  $("#oconfirm", m.body).onclick = async e => {
    const b = e.currentTarget; b.disabled = true;
    try { const r = await api("/outreach/approve-and-send", { method: "POST", body: { ids: list.map(o => o.id) } }); prevRunning = true; m.close();
      toast(`Sending ${r.approved}${r.skipped.length ? ` — ${r.skipped.length} skipped (${r.skipped[0].reason})` : ""}`, 5000); S.otab = "approved"; render(); }
    catch (x) { toast(x.message, 6000); b.disabled = false; }
  };
}
