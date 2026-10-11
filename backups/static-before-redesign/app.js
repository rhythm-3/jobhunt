"use strict";
/* JobAgent UI — vanilla JS, no build step. Talks only to the local FastAPI backend. */

// ---------------------------------------------------------------- helpers
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ls = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const pct = x => x == null ? "–" : Math.round(x * 100) + "%";
const band = x => x == null ? "s1" : x >= 0.55 ? "s3" : x >= 0.40 ? "s2" : "s1";          // bands match this scorer's scale
const bandName = x => ({ s3: "Strong", s2: "Good", s1: "Fair" })[band(x)];
const hue = s => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const initials = s => String(s || "?").replace(/[^A-Za-z0-9 ]/g, " ").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase() || "?";
const avatar = (co, domain) => `<div class="av" style="--h:${hue(co)}" aria-hidden="true">${esc(initials(co))}${domain && /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(domain)
  ? `<img src="https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64" alt="" loading="lazy" onload="this.parentNode.classList.add('logo')" onerror="this.remove()">` : ""}</div>`;
const src = j => esc(((j && j.source) || "").split(":")[0]);
function ago(v) {
  if (v == null) return "never";
  const s = typeof v === "number" ? v : (Date.now() - new Date(v).getTime()) / 1000;
  if (s < 60) return "just now"; if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago"; return Math.round(s / 86400) + "d ago";
}

const I = {  // lucide-style inline icons
  building: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10 21v-3h4v3"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></svg>',
  help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6"/><path d="M12 17h.01"/></svg>',
  bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>',
  collapse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18"/><path d="m15 10-2 2 2 2"/></svg>',
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/></svg>',
  pipe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="5" height="18" rx="1.5"/><rect x="10" y="3" width="5" height="12" rx="1.5"/><rect x="17" y="3" width="4" height="8" rx="1.5"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/></svg>',
  mail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/></svg>',
  cog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
  act: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  sparkle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 17l.8 2.2L22 20l-2.2.8L19 23l-.8-2.2L16 20l2.2-.8z"/></svg>',
  ext: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></svg>',
  form: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="6" rx="1"/><rect x="12" y="8" width="3" height="10" rx="1"/><rect x="17" y="5" width="3" height="13" rx="1"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 18v-6M9 14.5l3-3 3 3"/></svg>',
  reply: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 17l-5-5 5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>',
  cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
};
const EMPTY = {
  inbox: '<svg viewBox="0 0 120 120" fill="none"><rect x="18" y="34" width="84" height="56" rx="10" fill="var(--panel-2)" stroke="var(--line)" stroke-width="2"/><path d="M18 64h24l6 10h24l6-10h24" stroke="var(--mute)" stroke-width="2"/><circle cx="92" cy="30" r="10" fill="var(--emerald-bg)"/><path d="M88 30l3 3 5-6" stroke="var(--emerald)" stroke-width="2.5" stroke-linecap="round"/></svg>',
  cards: '<svg viewBox="0 0 120 120" fill="none"><rect x="22" y="30" width="60" height="40" rx="8" fill="var(--panel-2)" stroke="var(--line)" stroke-width="2" transform="rotate(-8 52 50)"/><rect x="36" y="44" width="62" height="42" rx="8" fill="var(--panel)" stroke="var(--line)" stroke-width="2"/><path d="M46 58h30M46 67h20" stroke="var(--mute)" stroke-width="3" stroke-linecap="round"/><circle cx="90" cy="84" r="12" fill="var(--violet-bg)"/><path d="M90 78v12M84 84h12" stroke="var(--violet)" stroke-width="2.5" stroke-linecap="round"/></svg>',
  done: '<svg viewBox="0 0 120 120" fill="none"><circle cx="60" cy="60" r="34" fill="var(--emerald-bg)"/><path d="M46 60l10 10 20-22" stroke="var(--emerald)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

// ---------------------------------------------------------------- api / toast
async function api(path, opts = {}) {
  const tok = ls.get("token");
  if (opts.method && opts.method !== "GET") S.loadedAt = 0;          // something is changing: the next screen must load fresh data
  const r = await fetch("/api" + path, { method: opts.method || "GET",
    headers: { "Content-Type": "application/json", ...(tok ? { Authorization: "Bearer " + tok } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (r.status === 401) { const t = prompt("Dashboard token"); if (t) { ls.set("token", t); return api(path, opts); } }
  if (!r.ok) { let d = r.statusText; try { const j = await r.json(); d = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {} throw new Error(d); }
  return r.json();
}
function toast(msg, ms = 2800) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; t.setAttribute("role", "status");
  $(".toasts").append(t); setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 320); }, ms);
}

// ---------------------------------------------------------------- state
const S = { view: "home", runs: [], stats: null, agents: null, settings: null, profile: null, emails: [],
            q: "", srcFilter: "", showLow: false, sweeping: false, sweepNote: "", drawer: null, animate: true,
            appsFilter: "active", mailFilter: "all", dirty: false, jobsTab: "ready", jobsLayout: ls.get("layout") || "list",
            setTab: "profile", lastCounts: null };
const VIEWS = [
  ["home", "Dashboard", I.home, "Pipeline"], ["jobs", "Jobs", I.pipe, "Pipeline"], ["applications", "Applications", I.send, "Pipeline"], ["interviews", "Interviews", I.cal, "Pipeline"],
  ["outreach", "Outreach", I.user, "People"], ["inbox", "Inbox", I.mail, "People"], ["companies", "Companies", I.building, "Research"], ["insights", "Insights", I.chart, "Research"],
  ["settings", "Settings", I.cog, "Account"], ["help", "Help", I.help, "Account"]];
const PAGE_TONE = { home: "accent", jobs: "sky", applications: "emerald", interviews: "violet", outreach: "amber", inbox: "rose", companies: "sky", insights: "violet", settings: "accent", help: "emerald" };
const MAIL_LABEL = { interview_request: "Interview", screening_questions: "Questions", rejection: "Rejection", auto_acknowledgement: "Confirmation", other: "Message" };
// email text for display: no inline-image codes, tracking links shortened to their site name
const cleanMail = t => String(t || "").replace(/\[cid:[^\]]*\]/g, " ").replace(/<(https?:\/\/[^>\s]+)>/g, " ")
  .replace(/https?:\/\/([^\/\s?#]+)[^\s)\]]{25,}/g, (_, host) => `(link: ${host.replace(/^www\./, "")})`).replace(/\*+/g, "").replace(/[ \t]{2,}/g, " ").trim();
const ACRONYMS = new Set("aws gcp siem soc soar edr xdr sql kql spl api apis llm rag iam dlp grc mitre ci/cd sast dast iac ids ips vpn waf pki sso mfa okta nist iso pci hipaa gdpr".split(" "));
const skillName = s => ACRONYMS.has(String(s).toLowerCase()) ? String(s).toUpperCase() : String(s).charAt(0).toUpperCase() + String(s).slice(1);
const SUBTITLE = { home: "What needs you today", jobs: "Matched roles, prepared applications and everything in between",
  applications: "Everything you've applied to, and what happened next", interviews: "Upcoming interviews, practice and offers", outreach: "Email recruiters directly, with your CV — and track every reply", inbox: "Recruiter replies, sorted and linked to your applications",
  companies: "Research every employer from public sources", insights: "What employers want, and how your search is converting",
  settings: "Your profile, preferences and accounts", help: "How it works, safety and answers" };
const ALIAS = { pipeline: ["jobs"], review: ["jobs", "ready"], customize: ["settings", "prefs"], profile: ["settings", "profile"], activity: ["settings", "activity"] };
// plain-language status names, used everywhere a status is shown
const STATUS = { scored: "New", skipped: "Low match", discovered: "Preparing…", tailored: "Preparing…", awaiting_approval: "Ready for you",
  approved: "Sending…", submitting: "Sending…", submitted: "Applied", needs_manual: "Not applied yet — apply on website", interview: "Interview",
  closed: "Closed", rejected: "Not pursued", failed: "Couldn't prepare", filtered: "Hidden by filters", offer: "Offer" };
// save preferences; the server re-applies them to jobs already in the list and says what moved
async function saveSettings(body) {
  const out = await api("/settings", { method: "PUT", body });
  const ap = out._applied || {}; delete out._applied; S.settings = out;
  const parts = [ap.hidden && `${ap.hidden} hidden by your filters`, ap.restored && `${ap.restored} back in your list`,
    ap.now_low_match && `${ap.now_low_match} moved to low matches`, ap.now_new_match && `${ap.now_new_match} moved to new matches`].filter(Boolean);
  S.runs = await api("/runs?lite=1"); S.stats = await api("/stats");
  return parts.length ? "Saved · " + parts.join(" · ") : "Saved · no jobs in your list changed";
}
const st = s => STATUS[s] || String(s || "").replace(/_/g, " ");

// ---------------------------------------------------------------- accessibility preferences (per browser)
const A11Y = { get() { try { return JSON.parse(ls.get("a11y") || "{}"); } catch { return {}; } },
  apply() { const a = this.get(), r = document.documentElement;
    r.dataset.text = a.text || "normal"; r.dataset.contrast = a.contrast ? "high" : ""; r.dataset.motion = a.motion ? "reduce" : ""; },
  set(k, v) { const a = this.get(); a[k] = v; ls.set("a11y", JSON.stringify(a)); this.apply(); } };

// ---------------------------------------------------------------- shell
function shell() {
  const B = window.BRAND || { name: "OfferPilot", logo: "" };
  const groups = [...new Set(VIEWS.map(v => v[3]))];
  document.body.innerHTML = `
  <a class="skip" href="#content">Skip to main content</a>
  <div class="app ${ls.get("navmini") === "1" ? "mini" : ""}">
    <nav class="side" aria-label="Main">
      <div class="brand"><span class="blogo">${B.logo}</span><span class="bname">${esc(B.name)}</span>
        <button class="icon-btn collapse" id="navmini" aria-label="Collapse sidebar" title="Collapse sidebar">${I.collapse}</button></div>
      ${groups.map(g => `<div class="navgroup"><div class="navlabel">${esc(g)}</div>${VIEWS.filter(v => v[3] === g).map(([k, l, ic]) =>
        `<button class="nav" data-v="${k}" aria-label="${l}" title="${l}">${ic}<span class="label">${l}</span><span class="count" data-count="${k}" hidden></span></button>`).join("")}</div>`).join("")}
      <div class="foot"><span class="mode" id="mode"></span></div>
    </nav>
    <div class="main">
      <header class="top">
        <button class="gsearch" id="cmdk" aria-label="Search jobs, companies and actions">${I.search}<span>Search jobs, companies, actions…</span><kbd class="kbd">⌘K</kbd></button>
        <span class="grow"></span>
        <button class="pill statusbtn" id="status" aria-haspopup="dialog" aria-expanded="false"><span class="dot live" id="sdot"></span><span id="stext">Checking…</span></button>
        <button class="icon-btn bellbtn" id="bell" aria-label="Notifications" aria-haspopup="dialog">${I.bell}<span class="bdg" id="bdg" hidden></span></button>
        <button class="icon-btn" id="theme" title="Theme" aria-label="Change theme">${I.moon}</button>
        <button class="acct" id="acct" aria-haspopup="menu" aria-expanded="false"><span class="acav" id="acav"></span></button>
        <button class="btn primary" id="refresh" data-refresh aria-label="Find new jobs"><span class="spin" aria-hidden="true">${I.refresh}</span><span class="rlabel">Find new jobs</span></button>
      </header>
      <div class="pagehead"><span class="pagebadge" id="pagebadge" aria-hidden="true"></span><div><h1 id="title"></h1><p id="subtitle"></p></div><div id="pageactions" class="row"></div></div>
      <main class="content" id="content" tabindex="-1"></main>
    </div>
  </div>
  <div class="toasts" role="status" aria-live="polite"></div>`;
  $$(".nav").forEach(b => b.onclick = () => go(b.dataset.v));
  $("#theme").onclick = () => {
    const order = Object.keys(THEMES), cur = curTheme();
    setTheme(order[(order.indexOf(cur) + 1) % order.length]);
  };
  setTheme(curTheme(), true);
  $("#refresh").onclick = refreshJobs;
  $("#cmdk").onclick = palette;
  $("#status").onclick = statusPop;
  $("#bell").onclick = bellPop;
  $("#acct").onclick = acctMenu;
  $("#navmini").onclick = () => { const app = $(".app"); app.classList.toggle("mini"); ls.set("navmini", app.classList.contains("mini") ? "1" : "0"); };
}

// ---------------------------------------------------------------- notifications (from the audit trail)
const NOTE_EVENTS = {
  node_done: e => e.detail && e.detail.status === "awaiting_approval" ? ["ready", "An application is ready for your review"] : null,
  classified: e => ({ interview_request: ["mail", "A recruiter wants to schedule an interview"], screening_questions: ["mail", "A recruiter asked you some questions"],
                      rejection: ["closed", "An application was declined"], auto_acknowledgement: ["ok", "A company confirmed your application"] })[e.detail && e.detail.label] || null,
  submitted: () => ["ok", "Application sent"], imported_application: e => ["ok", `Tracked an application to ${e.detail.company} from your email`],
  full_description_found: () => ["intel", "Found a full job description on a company careers site"],
  sweep_complete: e => e.detail && e.detail.new ? ["new", `${e.detail.new} new jobs found`] : null,
  escalated_to_human: () => ["ready", "An application needs you to apply on the company website"],
};
async function loadNotes() {
  const log = await api("/audit");
  return log.map(e => { const f = NOTE_EVENTS[e.event]; const r = f && f(e); return r ? { id: e.id, at: e.at, kind: r[0], text: r[1], run: e.run_id } : null; }).filter(Boolean).slice(0, 40);
}
async function refreshBell() {
  try { S.notes = await loadNotes(); } catch { return; }
  const seen = +(ls.get("seenNote") || 0), unread = S.notes.filter(n => n.id > seen).length;
  const b = $("#bdg"); if (!b) return;
  b.hidden = !unread; b.textContent = unread > 9 ? "9+" : unread;
  $("#bell").setAttribute("aria-label", `Notifications${unread ? `, ${unread} unread` : ""}`);
}
function bellPop(e) {
  const btn = e.currentTarget, old = $(".bellpop");
  if (old) { old.remove(); return; }
  const seen = +(ls.get("seenNote") || 0);
  const p = document.createElement("div"); p.className = "card bellpop"; p.setAttribute("role", "dialog"); p.setAttribute("aria-label", "Notifications");
  p.innerHTML = `<div class="row" style="padding:12px 14px;border-bottom:1px solid var(--line)"><b class="grow">Notifications</b><button class="btn sm ghost" id="markall">Mark all read</button></div>
    <div class="notes">${(S.notes || []).map(n => `<button class="note ${n.id > seen ? "unread" : ""}" ${n.run ? `data-open="${esc(n.run)}"` : ""}><span class="ndot k-${n.kind}"></span><span class="grow">${esc(n.text)}</span><span class="small muted">${esc(ago(n.at))}</span></button>`).join("")
      || '<p class="muted small" style="padding:16px">Nothing yet.</p>'}</div>`;
  document.body.append(p);
  const r = btn.getBoundingClientRect(); p.style.top = r.bottom + 8 + "px"; p.style.right = Math.max(12, innerWidth - r.right) + "px";
  const markAll = () => { ls.set("seenNote", String(Math.max(0, ...(S.notes || []).map(n => n.id)))); refreshBell(); };
  $("#markall", p).onclick = () => { markAll(); p.remove(); };
  $$("[data-open]", p).forEach(x => x.onclick = () => { p.remove(); markAll(); openDrawer(x.dataset.open); });
  setTimeout(() => document.addEventListener("click", function off(ev) { if (!p.contains(ev.target) && ev.target !== btn) { p.remove(); document.removeEventListener("click", off); } }), 0);
}
function acctMenu(e) {
  const btn = e.currentTarget, old = $(".acctpop");
  if (old) { old.remove(); btn.setAttribute("aria-expanded", "false"); return; }
  const p = document.createElement("div"); p.className = "card acctpop"; p.setAttribute("role", "menu");
  const pr = S.profile || {};
  p.innerHTML = `<div style="padding:12px 14px;border-bottom:1px solid var(--line)"><b>${esc(pr.full_name || "")}</b><div class="small muted">${esc(pr.email || "")}</div></div>
    ${[["profile", "Profile & resume"], ["prefs", "Job preferences"], ["accounts", "Gmail & sending"], ["a11y", "Accessibility & theme"]].map(([k, l]) =>
      `<button role="menuitem" class="mi" data-set="${k}">${l}</button>`).join("")}
    <button role="menuitem" class="mi" id="mi-setup">Run setup again</button><button role="menuitem" class="mi" id="mi-keys">Keyboard shortcuts</button>
    <a role="menuitem" class="mi" href="/welcome" target="_blank" rel="noopener">About ${esc((window.BRAND || {}).name || "")}</a>`;
  document.body.append(p);
  const r = btn.getBoundingClientRect(); p.style.top = r.bottom + 8 + "px"; p.style.right = Math.max(12, innerWidth - r.right) + "px";
  btn.setAttribute("aria-expanded", "true"); $(".mi", p).focus();
  const close = () => { p.remove(); btn.setAttribute("aria-expanded", "false"); };
  $$("[data-set]", p).forEach(x => x.onclick = () => { close(); S.setTab = x.dataset.set; go("settings"); });
  $("#mi-setup", p).onclick = () => { close(); onboarding(true); };
  $("#mi-keys", p).onclick = () => { close(); shortcuts(); };
  p.addEventListener("keydown", ev => { if (ev.key === "Escape") { close(); btn.focus(); }
    if (["ArrowDown", "ArrowUp"].includes(ev.key)) { ev.preventDefault(); const it = $$(".mi", p), i = it.indexOf(document.activeElement); it[(i + (ev.key === "ArrowDown" ? 1 : -1) + it.length) % it.length].focus(); } });
  setTimeout(() => document.addEventListener("click", function off(ev) { if (!p.contains(ev.target) && !btn.contains(ev.target)) { close(); document.removeEventListener("click", off); } }), 0);
}

const THEMES = { studio: "Light", night: "Dark", neo: "Futuristic" };
const THEME_BASE = { studio: "light", night: "dark" };          // a skin is a base theme plus its own palette
const curTheme = () => document.documentElement.dataset.skin || document.documentElement.dataset.theme || "studio";
function setTheme(n, quiet = false) {
  if (!THEMES[n]) n = "studio";
  const root = document.documentElement;
  root.dataset.theme = THEME_BASE[n] || n; if (THEME_BASE[n]) root.dataset.skin = n; else delete root.dataset.skin;
  if (n === "studio" || n === "night") root.dataset.ui = "studio"; else delete root.dataset.ui;
  ls.set("theme", n);
  const b = $("#theme"); if (b) { b.title = `Theme: ${THEMES[n]} (click to change)`; b.setAttribute("aria-label", `Theme: ${THEMES[n]}. Click to change`); }
  if (!quiet) toast(`${THEMES[n]} theme`);
}

function go(v, push = true) {
  const [view, sub] = ALIAS[v] || [v];
  if (view === "jobs" && sub) S.jobsTab = sub;
  if (view === "settings" && sub) S.setTab = sub;
  S.view = VIEWS.some(x => x[0] === view) ? view : "home"; S.animate = true;
  if (push) history.replaceState(null, "", "#" + S.view);
  (typeof smoothRender === "function" ? smoothRender() : render()).then(() => { const c = $("#content"); if (push && c) c.focus({ preventScroll: true }); });
}

// ---------------------------------------------------------------- data
async function load() {
  const [stats, agents, runs, emails, pulse] = await Promise.all([api("/stats"), api("/agents"), api("/runs?lite=1"), api("/inbox").catch(() => S.emails || []), api("/pulse").catch(() => null)]);
  Object.assign(S, { stats, agents, runs, emails, loadedAt: Date.now(), pulse: pulse && pulse.sig });
  if (!S.settings) S.settings = await api("/settings");
  if (!S.profile) S.profile = await api("/profile");
}

function agentLines() {
  const a = S.agents, b = S.stats.by_status, tq = a.tailoring.queue + b.discovered + b.tailored;
  return [
    [a.sourcing.running ? "busy" : "live", "Finding jobs", a.sourcing.running ? "searching now…" : `last checked ${ago(a.sourcing.last_s_ago)}${a.sourcing.every_h ? `, repeats every ${a.sourcing.every_h}h` : ""}`],
    [tq ? "busy" : "live", "Preparing applications", tq ? `${tq} in progress (${a.tailoring.provider === "ollama" ? a.tailoring.model : a.tailoring.provider})` : `idle (${a.tailoring.provider === "ollama" ? a.tailoring.model : a.tailoring.provider})`],
    [a.triage.polling ? "live" : "off", "Reading your inbox", a.triage.polling ? `checked ${ago(a.triage.last_s_ago)}` : "off"],
    [a.dispatch.dry_run ? "warn" : "live", "Sending", a.dispatch.dry_run ? "practice mode — nothing is actually sent" : "live — approved applications are emailed"],
  ];
}
function chrome() {
  const a = S.agents, b = S.stats.by_status;
  $("#mode").className = "mode " + (a.dispatch.dry_run ? "dry" : "live");
  $("#mode").textContent = a.dispatch.dry_run ? "Practice mode" : "Live sending";
  $("#mode").title = a.dispatch.dry_run ? "Nothing is actually sent. Restart with DRY_RUN=0 to send for real." : "Approved applications are really sent";

  const busy = a.sourcing.running || a.tailoring.queue + b.discovered + b.tailored > 0;
  $("#sdot").className = "dot " + (busy ? "busy" : "live");
  $("#stext").textContent = a.sourcing.running ? "Finding jobs…" : busy ? "Preparing applications…" : "All agents ready";
  const review = b.awaiting_approval + b.needs_manual;
  const actionable = S.emails.filter(m => ["interview_request", "screening_questions"].includes(m.label) && !m.replied_at).length;
  for (const [k, n] of [["jobs", review], ["inbox", actionable]]) { const c = $(`[data-count="${k}"]`); c.hidden = !n; c.textContent = n; c.setAttribute("aria-label", `${n} need you`); }
  $$(".nav").forEach(n => n.dataset.v === S.view ? n.setAttribute("aria-current", "page") : n.removeAttribute("aria-current"));
  $("#title").textContent = S.view === "home" ? `${greeting()}${S.profile && S.profile.full_name ? ", " + (n => n === n.toUpperCase() ? n[0] + n.slice(1).toLowerCase() : n)(S.profile.full_name.split(" ")[0]) : ""}` : (VIEWS.find(v => v[0] === S.view) || VIEWS[0])[1];
  const pv = VIEWS.find(v => v[0] === S.view) || VIEWS[0], pb = $("#pagebadge");
  if (pb) { pb.innerHTML = pv[2]; pb.dataset.tone = PAGE_TONE[S.view] || "accent"; }
  $("#subtitle").textContent = SUBTITLE[S.view] || "";
  $("#acav").textContent = initials((S.profile || {}).full_name || "?");
  document.title = (review ? `(${review}) ` : "") + ((window.BRAND || {}).name || "OfferPilot");
  refreshBell();
  $$("[data-refresh]").forEach(x => { x.classList.toggle("busy", S.sweeping); x.disabled = S.sweeping; });
  notifyChanges(review, actionable);
}
function statusPop(e) {
  const btn = e.currentTarget, old = $(".statuspop");
  if (old) { old.remove(); btn.setAttribute("aria-expanded", "false"); return; }
  const p = document.createElement("div"); p.className = "card statuspop"; p.setAttribute("role", "dialog"); p.setAttribute("aria-label", "Agent status");
  p.innerHTML = `<b>What's running</b>${agentLines().map(([d, n, t]) => `<div class="row" style="margin-top:10px;flex-wrap:nowrap"><span class="dot ${d}"></span><div><div>${esc(n)}</div><div class="small muted">${esc(t)}</div></div></div>`).join("")}`;
  document.body.append(p);
  const r = btn.getBoundingClientRect(); p.style.top = r.bottom + 8 + "px"; p.style.left = Math.min(r.left, innerWidth - 320) + "px";
  btn.setAttribute("aria-expanded", "true");
  setTimeout(() => document.addEventListener("click", function off(ev) { if (!p.contains(ev.target)) { p.remove(); btn.setAttribute("aria-expanded", "false"); document.removeEventListener("click", off); } }), 0);
}

// ---------------------------------------------------------------- desktop notifications (opt-in)
function notifyChanges(review, replies) {
  const prev = S.lastCounts; S.lastCounts = { review, replies };
  if (!prev || !A11Y.get().notify || !("Notification" in window) || Notification.permission !== "granted") return;
  if (review > prev.review) new Notification("JobAgent", { body: `${review - prev.review} new application${review - prev.review > 1 ? "s" : ""} ready for you` });
  if (replies > prev.replies) new Notification("JobAgent", { body: "A recruiter replied — check your inbox" });
}

async function render() {
  const fresh = S.runs && S.stats && Date.now() - (S.loadedAt || 0) < 10000;      // switching pages reuses data loaded moments ago
  if (!fresh) try { await load(); } catch (e) { $("#content").innerHTML = `<div class="card empty big">${EMPTY.cards}<b>Can't reach the JobAgent server</b><span>${esc(e.message)}</span><span>Start it with <code>python3 run.py</code> in the job-agent folder.</span></div>`; return; }
  chrome(); hideUpdatesPill();
  // Each render draws into its own copy of the content area. A slower page that finishes late then writes into a
  // detached copy and can never overwrite the page you are on now.
  const prev = $("#content"), c = prev.cloneNode(true);
  prev.replaceWith(c);
  c.classList.toggle("noanim", !S.animate);
  const fn = { home: vHome, jobs: vJobs, applications: vApps, interviews: vInterviews, outreach: vOutreach, inbox: vInbox, companies: vCompanies, insights: vInsights, settings: vSettingsHub, help: vHelp }[S.view] || vHome;
  $("#pageactions").innerHTML = "";
  await fn(c);
  S.animate = false;
}

// ---------------------------------------------------------------- refresh (sourcing)
async function refreshJobs() {
  if (S.sweeping) return;
  S.sweeping = true; S.sweepNote = "Fetching job feeds, company career sites and your alert emails…"; chrome(); noteUpd();
  try {
    let s = await api("/sweep", { method: "POST" });
    while (s.running) { await sleep(1500); s = await api("/sweep/status"); }
    const r = s.result || s;
    if (r.error) throw new Error(r.error);
    const parts = Object.entries(r.by_source || {}).map(([k, n]) => `${n} ${k}`).join(" · ");
    S.sweepNote = r.discovered ? `${r.discovered} new from ${r.sources} sources — ${parts}` : `Up to date · checked ${r.sources} sources`;
    const cs = r.company_sites;
    if (cs && cs.boards) S.sweepNote += ` · company sites: ${cs.fetched} openings read, ${cs.matched} fit your filters, ${cs.new} new`;
    if (r.queued) S.sweepNote += ` · ${r.queued} best matches tailoring`;
    if ((r.failed_sources || []).length) S.sweepNote += ` · unreachable: ${r.failed_sources.join(", ")}`;
    toast(r.discovered ? `✨ ${r.discovered} new jobs` : "No new jobs right now");
  } catch (e) { S.sweepNote = "Refresh failed: " + e.message; toast(S.sweepNote); }
  S.sweeping = false; S.animate = true; render();
}
// a refresh the server started by itself (after a resume change): show it in the status, then load the new jobs
async function watchSweep() {
  S.sweeping = true; chrome();
  try { let s = await api("/sweep/status"); for (let i = 0; i < 120 && s.running; i++) { await sleep(2500); s = await api("/sweep/status"); }
    const r = s.result || {}; S.sweepNote = r.discovered ? `${r.discovered} new jobs for your updated resume` : "Up to date for your updated resume"; toast(r.discovered ? `✨ ${r.discovered} new jobs for your updated resume` : "No new jobs right now"); }
  catch {} finally { S.sweeping = false; S.loadedAt = 0; render(); }
}
function noteUpd() { const n = $("#sweepnote"); if (n) n.textContent = S.sweepNote; }

// ---------------------------------------------------------------- pipeline
const COLS = [
  { k: "discovered", label: "Discovered", c: "var(--sky)", st: ["scored"] },
  { k: "review", label: "Ready for review", c: "var(--amber)", st: ["awaiting_approval", "needs_manual", "discovered", "tailored"], hot: true },
  { k: "applied", label: "Applied", c: "var(--accent)", st: ["approved", "submitting", "submitted"] },
  { k: "interview", label: "Interviews & offers", c: "var(--emerald)", st: ["interview", "offer"] },
  { k: "closed", label: "Closed", c: "var(--mute)", st: ["rejected", "closed", "failed"] },
];
function matches(r) {
  const j = r.job || {}, q = S.q.toLowerCase(), f = S.jf || {};
  if (q && !`${j.title} ${j.company} ${j.location}`.toLowerCase().includes(q)) return false;
  if (S.srcFilter && !(j.source || "").startsWith(S.srcFilter)) return false;
  if (f.remote && !j.remote) return false;
  if (f.minScore && (r.match_score || 0) < f.minScore) return false;
  if (f.minLpa && !(r.salary && r.salary.currency === "INR" && r.salary.max >= f.minLpa)) return false;
  if (f.fullDesc && !j.enriched_from && (j.desc_len ?? (j.description || "").length) < 600) return false;
  return true;
}
const activeFilters = () => { const f = S.jf || {}; return [f.remote, f.minScore, f.minLpa, f.fullDesc, S.srcFilter].filter(Boolean).length; };
function scoreBadge(s, st_) {
  if (s == null) return "";
  return `<span class="score ${band(s)}" title="${bandName(s)} match">${bandName(s)} ${pct(s)}</span>`;
}
function stepperHtml(status) {
  const at = { scored: 0, skipped: 0, discovered: 0, tailored: 0, awaiting_approval: 1, needs_manual: 1, approved: 2, submitting: 2, submitted: 2, interview: 3, offer: 4 }[status];
  if (at == null) return "";
  const steps = ["Matched", "Review", "Sent", "Interview", "Offer"];
  return `<ol class="stepper" aria-label="Progress">${steps.map((l, i) => `<li class="${i < at ? "done" : i === at ? "now" : ""}" ${i === at ? 'aria-current="step"' : ""}><span class="dotn">${i < at ? "✓" : i + 1}</span>${l}</li>`).join("")}</ol>`;
}
function scoreRing(s) {
  if (s == null) return "";
  const c = band(s) === "s3" ? "var(--emerald)" : band(s) === "s2" ? "var(--amber)" : "var(--mute)", C = 2 * Math.PI * 19;
  return `<span class="sring" role="img" aria-label="${bandName(s)} match, ${pct(s)}" title="${bandName(s)} match"><svg viewBox="0 0 46 46" width="46" height="46" aria-hidden="true"><circle cx="23" cy="23" r="19" fill="none" stroke="var(--line)" stroke-width="4"/>
    <circle cx="23" cy="23" r="19" fill="none" stroke="${c}" stroke-width="4" stroke-linecap="round" pathLength="100" class="arc" stroke-dasharray="${Math.round(Math.min(1, s / 0.9) * 100)} 100" transform="rotate(-90 23 23)"/></svg><b>${Math.round(s * 100)}</b><em>${bandName(s)}</em></span>`;
}
function primaryAction(r) {
  const s = r.status;
  if (s === "scored" || s === "skipped") return `<button class="btn sm" data-tailor="${esc(r.id)}">${I.sparkle}Prepare application</button>`;
  if (s === "awaiting_approval") return `<button class="btn sm primary" data-open="${esc(r.id)}">Review &amp; send</button>`;
  if (s === "needs_manual") return `<button class="btn sm primary" data-open="${esc(r.id)}">${I.form}Apply on website</button>`;
  if (s === "failed") return `<button class="btn sm" data-open="${esc(r.id)}">Try again</button>`;
  return `<button class="btn sm ghost" data-open="${esc(r.id)}">Details</button>`;
}
function card(r, i) {
  const j = r.job || {}, s = r.match_score, stt = r.status;
  const flag = stt === "needs_manual" ? "Apply on website" : stt === "failed" ? "Couldn't prepare" : r.follow_up_due ? "Follow up" : ["discovered", "tailored"].includes(stt) ? "Preparing…" : "";
  return `<article class="jc" tabindex="0" style="--i:${Math.min(i, 20)}" data-open="${esc(r.id)}" aria-label="${esc(j.title)} at ${esc(j.company)}, ${esc(st(stt))}">
    ${flag ? `<span class="flag">${esc(flag)}</span>` : ""}
    <div class="hd">${avatar(j.company, r.domain)}<div style="min-width:0"><h3>${esc(j.title)}</h3><div class="co">${esc(j.company)}</div></div>${scoreBadge(s, stt)}</div>
    <div class="meta">${j.location ? `<span class="chip">${esc(j.location.slice(0, 28))}</span>` : ""}${j.remote ? '<span class="chip info">Remote</span>' : ""}
      ${r.salary ? `<span class="chip ok">${esc(r.salary.label)}</span>` : ""}<span class="chip">${src(j)}</span></div>
    <div class="actions">${primaryAction(r)}</div>
  </article>`;
}
function row(r, i) {
  const j = r.job || {};
  return `<div class="card jrow" style="--i:${Math.min(i, 25)}" data-open="${esc(r.id)}" tabindex="0" role="button" aria-label="${esc(j.title)} at ${esc(j.company)}. ${esc(st(r.status))}. ${r.match_score != null ? bandName(r.match_score) + " match" : ""}">
    ${avatar(j.company, r.domain)}
    <div class="jmain"><h3>${r.starred ? '<span class="starmark" title="Starred">★</span> ' : ""}${esc(j.title)}</h3>
      <div class="jsub">${esc(j.company)}${j.location ? ` · ${esc(j.location.slice(0, 40))}` : ""}</div>
      <div class="meta">${r.salary ? `<span class="chip ok">${esc(r.salary.label)}</span>` : ""}${j.remote ? '<span class="chip info">Remote</span>' : ""}
        ${j.enriched_from ? `<span class="chip ai" title="Full description found on the company's own careers site">${I.shield.replace("<svg", '<svg width="12" height="12"')} Full description</span>` : ""}
        ${r.follow_up_due ? '<span class="chip warn">Follow-up due</span>' : ""}${r.status === "filtered" && r.last_error ? `<span class="chip warn">${esc(r.last_error)}</span>` : ""}
        <span class="small muted">${j.rating ? `★ ${esc(j.rating)} · ` : ""}${src(j)} · ${esc(ago(r.created_at))}</span>${fitBar(r)}</div></div>
    <div class="jside">${scoreRing(r.match_score)}${primaryAction(r)}</div>
  </div>`;
}
// ---- jobs from the same company fold into one expandable container
const coKey = r => ((r.job || {}).company || "").trim().toLowerCase() || r.id;
function groupByCompany(rs) {                        // a company sits where its best job ranks
  const m = new Map();
  for (const r of rs) { const k = coKey(r); if (!m.has(k)) m.set(k, []); m.get(k).push(r); }
  return [...m.values()];
}
function companyGroup(g, i) {
  if (g.length === 1) return row(g[0], i);
  const j = g[0].job || {}, key = coKey(g[0]), open = (S.openCos || (S.openCos = new Set())).has(key) || !!S.q;
  const scores = g.map(r => r.match_score).filter(x => x != null), best = scores.length ? Math.max(...scores) : null;
  const locs = [...new Set(g.map(r => (r.job.location || "").split(/[,;]/)[0].trim()).filter(Boolean))];
  const id = "co-" + key.replace(/[^a-z0-9]+/g, "-");
  return `<section class="card cogroup ${open ? "open" : ""}" style="--i:${Math.min(i, 25)}">
    <button class="cohead" data-co="${esc(key)}" aria-expanded="${open}" aria-controls="${id}">
      ${avatar(j.company, g[0].domain)}
      <span class="jmain"><b class="coname">${esc(j.company)}</b>
        <span class="jsub">${g.length} openings${locs.length ? " · " + esc(locs.slice(0, 2).join(", ")) + (locs.length > 2 ? ` +${locs.length - 2} more` : "") : ""}</span>
        <span class="small muted copreview">${g.slice(0, 2).map(r => esc(r.job.title)).join(" · ")}${g.length > 2 ? " …" : ""}</span></span>
      <span class="jside">${best != null ? `<span class="small muted">best match</span>${scoreRing(best)}` : ""}<span class="chev" aria-hidden="true">›</span></span>
    </button>
    ${open ? `<div class="cobody" id="${id}">${g.map((r, k) => row(r, k)).join("")}</div>` : ""}</section>`;
}
function bindCards(root) {
  $$("[data-open]", root).forEach(el => {
    el.onclick = e => { if (e.target.closest("[data-tailor],[data-form]") || (e.target.closest("[data-open]") !== el)) return; e.stopPropagation(); openDrawer(el.dataset.open); };
    el.onkeydown = e => { if (e.key === "Enter") openDrawer(el.dataset.open); };
  });
  $$("[data-tailor]", root).forEach(b => b.onclick = async e => {
    e.stopPropagation(); b.disabled = true; b.innerHTML = `<span class="spin" style="animation:spin .9s linear infinite">${I.refresh}</span>Preparing…`; b.parentElement.parentElement.classList.add("busy");
    try { const r = await api(`/runs/${b.dataset.tailor}/tailor`, { method: "POST" }); toast(r.queued ? `Preparing — about a minute${r.position > 1 ? ` (${r.position} in line)` : ""}` : "Application prepared"); }
    catch (x) { toast(x.message); b.disabled = false; b.textContent = "Prepare application"; }
  });
  $$("[data-form]", root).forEach(b => b.onclick = e => { e.stopPropagation(); openForm(b.dataset.form); });
}
// ---------------------------------------------------------------- home
function greeting() { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; }
async function vHome(c) {
  const [ivs, offers, prog, outr, trend, people] = await Promise.all([api("/interviews").catch(() => []), api("/offers").catch(() => []), api("/progress").catch(() => null), api("/outreach").catch(() => null), api("/trends?days=84").catch(() => null), api("/contacts").catch(() => [])]);
  const last14 = k => trend ? trend[k].slice(-14) : null;
  if (!S.health) S.health = await api("/profile/health").catch(() => null);
  const b = S.stats.by_status, a = S.agents, R = S.runs, now = Date.now();
  const soon = ivs.filter(i => i.status === "scheduled" && new Date(i.starts_at) > now && new Date(i.starts_at) - now < 48 * 3600e3);
  const thanks = ivs.filter(i => i.status !== "cancelled" && !i.thank_you_sent_at && new Date(i.starts_at).getTime() + i.duration_min * 60e3 < now && now - new Date(i.starts_at) < 4 * 86400e3);
  const deciding = offers.filter(o => ["considering", "negotiating"].includes(o.status) && o.deadline && new Date(o.deadline + "T23:59") - now < 3 * 86400e3 && new Date(o.deadline + "T23:59") > now);
  const upcoming = ivs.filter(i => i.status === "scheduled" && new Date(i.starts_at).getTime() + i.duration_min * 60e3 > now).slice(0, 3);
  const ready = b.awaiting_approval, onSite = b.needs_manual;
  const replies = S.emails.filter(m => ["interview_request", "screening_questions"].includes(m.label) && !m.replied_at);
  const follow = R.filter(r => r.follow_up_due);
  const strongNew = R.filter(r => r.status === "scored" && (r.match_score || 0) >= 0.45);
  const stale = a.sourcing.last_s_ago == null || a.sourcing.last_s_ago > 12 * 3600;
  const steps = [
    ...soon.map(iv => ({ icon: I.cal, tone: "emerald", title: `Interview with ${iv.company} ${rel(iv.starts_at)}`, text: "Review your prep kit and practise two answers out loud.", btn: "Prepare",
      go: () => { S.ivTab = "practice"; S.practiceRun = iv.run_id; go("interviews"); } })),
    outr && outr.stats.follow_ups_due && { icon: I.reply, tone: "violet", title: `${outr.stats.follow_ups_due} recruiter email${outr.stats.follow_ups_due > 1 ? "s" : ""} to follow up on`,
      text: "No reply yet after 5 days — one friendly nudge is fine.", btn: "Follow up", go: () => { S.otab = "due"; go("outreach"); } },
    people.filter(x => x.due).length && { icon: I.user, tone: "sky", title: `${people.filter(x => x.due).length} ${people.filter(x => x.due).length > 1 ? "people" : "person"} to follow up with`,
      text: people.filter(x => x.due).slice(0, 3).map(x => x.name).join(", "), btn: "Open People", go: () => { S.oMode = "people"; go("outreach"); } },
    outr && outr.stats.approved && { icon: I.send, tone: "sky", title: `${outr.stats.approved} approved outreach email${outr.stats.approved > 1 ? "s are" : " is"} waiting to send`,
      text: "They go out one at a time, within your daily limit.", btn: "Open Outreach", go: () => { S.otab = "approved"; go("outreach"); } },
    ...thanks.map(iv => ({ icon: I.mail, tone: "violet", title: `Send a thank-you note to ${iv.company}`, text: "Best within 24 hours of the interview — we'll draft it for you.", btn: "Write it", go: () => thankYou(iv) })),
    ...deciding.map(o => ({ icon: I.check, tone: "amber", title: `Decide on the ${o.company} offer by ${new Date(o.deadline + "T00:00").toLocaleDateString([], { day: "numeric", month: "short" })}`,
      text: "Compare it with your other options and negotiate if it's worth it.", btn: "Compare", go: () => { S.ivTab = "offers"; go("interviews"); } })),
    ready && { icon: I.check, tone: "amber", title: `${ready} application${ready > 1 ? "s are" : " is"} ready for you`, text: "Resume and cover letter are written. Read them, edit if you like, then send.", btn: "Review now", go: () => go("review") },
    onSite && { icon: I.form, tone: "amber", title: `Apply on the company website for ${onSite} job${onSite > 1 ? "s" : ""}`, text: "We'll open the form and fill in your details — you press Submit.", btn: "Open", go: () => go("review") },
    replies.length && { icon: I.mail, tone: "emerald", title: `${replies.length} recruiter email${replies.length > 1 ? "s need" : " needs"} a reply`, text: "We can draft the reply for you.", btn: "Open inbox", go: () => { S.mailFilter = "all"; go("inbox"); } },
    follow.length && { icon: I.send, tone: "sky", title: `${follow.length} application${follow.length > 1 ? "s have" : " has"} had no reply`, text: `No answer for ${S.settings.follow_up_days}+ days. A short follow-up often helps.`, btn: "See them", go: () => { S.appsFilter = "followup"; go("applications"); } },
    strongNew.length && { icon: I.sparkle, tone: "violet", title: `${strongNew.length} strong new match${strongNew.length > 1 ? "es" : ""}`, text: "Prepare an application for the ones you like — about a minute each.", btn: "See matches", go: () => { S.jobsTab = "new"; go("jobs"); } },
    S.health && S.health.score < 75 && { icon: I.user, tone: "sky", title: `Strengthen your resume (health ${S.health.score}/100)`, text: "A few specific fixes make every tailored application better.", btn: "See fixes",
      go: () => { S.setTab = "profile"; go("settings"); } },
    stale && { icon: I.refresh, tone: "sky", title: "Look for new jobs", text: `Last search: ${ago(a.sourcing.last_s_ago)}. Checks job boards, company career sites and your job-alert emails.`, btn: "Find new jobs", go: refreshJobs },
  ].filter(Boolean);
  const setup = [
    ["Upload your resume", S.profile && S.profile.full_name !== "Alex Morgan", () => { S.setTab = "profile"; go("settings"); }],
    ["Connect Gmail", a.dispatch.gmail, () => { S.setTab = "accounts"; go("settings"); }],
    ["Find your first jobs", R.length > 0, refreshJobs],
    ["Prepare an application", R.some(r => r.adaptation), () => { S.jobsTab = "new"; go("jobs"); }],
    ["Send your first application", R.some(r => r.channel && r.channel !== "external"), () => go("review")],
    ["Turn on real sending", !a.dispatch.dry_run, () => toast("Restart the app with DRY_RUN=0 python3 run.py", 6000)],
  ];
  const done = setup.filter(x => x[1]).length;
  const top = R.filter(r => ["awaiting_approval", "scored"].includes(r.status)).sort((x, y) => (y.match_score || 0) - (x.match_score || 0)).slice(0, 3);
  const first = (S.profile.full_name || "").split(" ")[0];
  c.innerHTML = `<div class="view home">
    <p class="hello">${new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })} · ${a.dispatch.dry_run ? "Practice mode — nothing is sent for real yet" : "Live — approved applications are sent"}</p>
    ${(() => {
      const stages = [["Found for you", b.scored, "new", "sky", I.search, "matches to look at", "found"], ["Ready to send", ready + onSite, "review", "amber", I.check, "waiting for your OK", null],
        ["Applied", b.submitted, "applied", "accent", I.send, "sent, awaiting reply", "applied"], ["Interviews", ivs.filter(i => i.status === "scheduled" && new Date(i.starts_at) > now).length || b.interview, "interviews", "emerald", I.cal, "coming up", "interviews"],
        ["Offers", b.offer || 0, "offer", "violet", I.sparkle, "to decide on", "offers"]];
      const mx = Math.max(1, ...stages.map(x => x[1] || 0));
      return `<div class="journey" role="list" aria-label="Your job search pipeline">${stages.map(([l, n, k, tone, ic, sub, series], i) =>
        `<button class="stage t-${tone}" role="listitem" data-tile="${k}" style="--i:${i}"><span class="sico" aria-hidden="true">${ic}</span><b data-count="${n || 0}">${n || 0}</b><span class="sl">${l}</span><small>${sub}</small>
          ${series && last14(series) ? sparkline(last14(series), l) : `<span class="sbar" aria-hidden="true"><i style="width:${Math.max(n ? 10 : 0, Math.round((n || 0) / mx * 100))}%"></i></span>`}</button>`).join("")}</div>`; })()}
    <div class="homegrid">
      <section><h2 class="h">Your next steps</h2>
        ${steps.length ? `<ol class="steps">${steps.map((s, i) => `<li class="card step" style="--i:${i}"><span class="sico t-${s.tone}" aria-hidden="true">${s.icon}</span>
          <div class="grow"><b>${esc(s.title)}</b><div class="muted small">${esc(s.text)}</div></div><button class="btn ${i === 0 ? "primary" : ""}" data-step="${i}">${esc(s.btn)}</button></li>`).join("")}</ol>`
          : `<div class="card empty big">${EMPTY.done}<b>You're all caught up</b><span>We'll show your next steps here as jobs and replies arrive.</span></div>`}
        <h2 class="h" style="margin-top:22px">Best matches right now</h2>
        <div class="list">${top.map(row).join("") || `<div class="card empty">${EMPTY.cards}No matches yet — click Find new jobs</div>`}</div>
      </section>
      <aside>
        ${prog ? goalCard(prog, trend) : ""}
        ${upcoming.length ? `<section class="card sec"><h3>Upcoming interviews</h3>${upcoming.map(i => `<button class="mailmini" data-upiv><span class="chip ok">${esc(new Date(i.starts_at).toLocaleDateString([], { day: "numeric", month: "short" }))}</span>
            <b>${esc(i.company)}</b><span class="muted small">${esc(fmtWhen(i.starts_at))} · ${esc(rel(i.starts_at))}</span></button>`).join("")}</section>` : ""}
        ${done < setup.length ? `<section class="card sec"><h3>Getting started</h3><p>${done} of ${setup.length} done</p>
          <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="${setup.length}" aria-valuenow="${done}" aria-label="Setup progress"><i style="width:${done / setup.length * 100}%"></i></div>
          <ul class="check">${setup.map(([l, ok], i) => `<li class="${ok ? "ok" : ""}"><span aria-hidden="true">${ok ? "✓" : i + 1}</span>${ok ? `<s>${esc(l)}</s><span class="sr"> (done)</span>` : `<button class="linkbtn" data-setup="${i}">${esc(l)}</button>`}</li>`).join("")}</ul></section>` : ""}
        <section class="card sec"><h3>Latest from recruiters</h3>
          ${S.emails.slice(0, 4).map(m => `<button class="mailmini" data-mailgo><span class="chip lbl-${esc(m.label)}">${esc(({ interview_request: "Interview", screening_questions: "Questions", rejection: "Rejection", auto_acknowledgement: "Received" })[m.label] || "Email")}</span>
            <b>${esc(m.company || m.sender)}</b><span class="muted small">${esc(m.subject.slice(0, 60))}</span></button>`).join("") || '<p class="muted small">No recruiter mail yet.</p>'}</section>
      </aside>
    </div></div>`;
  countUp(c);
  $$("[data-step]", c).forEach(b => b.onclick = () => steps[+b.dataset.step].go());
  $$("[data-setup]", c).forEach(b => b.onclick = () => setup[+b.dataset.setup][2]());
  $$("[data-tile]", c).forEach(b => b.onclick = () => { const k = b.dataset.tile; if (k === "review") go("review"); else if (k === "interviews") { S.ivTab = "upcoming"; go("interviews"); } else { S.jobsTab = k; go("jobs"); } });
  const gs = $("#goalset", c); if (gs) gs.onclick = () => { S.setTab = "prefs"; go("settings"); };
  $$("[data-upiv]", c).forEach(x => x.onclick = () => { S.ivTab = "upcoming"; go("interviews"); });
  $$("[data-mailgo]", c).forEach(b => b.onclick = () => go("inbox"));
  bindCards(c);
}

// ---------------------------------------------------------------- jobs (list by default, board optional)
const _pay = r => r.salary && r.salary.currency === "INR" ? r.salary.max : -1;          // jobs without stated pay go last
const _txt = (a, b) => String(a || "").localeCompare(String(b || ""), undefined, { sensitivity: "base" });
const _score = (a, b) => (b.match_score || 0) - (a.match_score || 0);
const JOB_SORTS = {
  match: ["Best match", _score, "best matches first"],
  newest: ["Newest", (a, b) => new Date(b.created_at) - new Date(a.created_at) || _score(a, b), "newest first"],
  salary: ["Highest pay", (a, b) => _pay(b) - _pay(a) || _score(a, b), "highest stated pay first"],
  company: ["Company A–Z", (a, b) => _txt(a.job && a.job.company, b.job && b.job.company) || _score(a, b), "by company"],
  title: ["Job title A–Z", (a, b) => _txt(a.job && a.job.title, b.job && b.job.title) || _score(a, b), "by job title"],
};
const MAIN_TABS = ["ready", "new", "preparing", "applied", "interview", "offer"];
const JOB_TABS = [
  ["ready", "Ready for you", ["awaiting_approval", "needs_manual"], "Written and waiting for your OK. Open one to read the resume and cover letter, then send."],
  ["new", "New matches", ["scored"], "Jobs matched to your profile. Click “Prepare application” on the ones you like — about a minute each."],
  ["preparing", "Preparing", ["discovered", "tailored"], "The AI is writing these right now."],
  ["applied", "Applied", ["approved", "submitting", "submitted"], "Sent. Replies show up in your Inbox automatically."],
  ["interview", "Interviews", ["interview"], "A recruiter wants to talk. Check the Interview prep tab inside each job."],
  ["closed", "Closed", ["closed", "rejected", "failed"], "Finished or not pursued."],
  ["offer", "Offers", ["offer"], "Congratulations — compare and negotiate them in Interviews › Offers."],
  ["starred", "Starred", null, "Jobs you starred."],
  ["low", "Low matches", ["skipped"], "Below your minimum match score. You can still prepare any of them."],
  ["hidden", "Hidden by filters", ["filtered"], "These don't meet your current job preferences (salary, location, company, keywords…). Change them in Settings › Job preferences and they come back automatically."],
];
async function vJobs(c) {
  const draw = () => {
    const tab = JOB_TABS.find(x => x[0] === S.jobsTab) || JOB_TABS[0];
    const inTab = r => tab[2] ? tab[2].includes(r.status) : r.starred;
    $("#pageactions").innerHTML = `<button class="btn" id="quickrev" title="Go through new matches one at a time">Quick review</button><button class="btn" id="addjob" title="Paste a job from any website">+ Add a job</button>`;
    $("#addjob").onclick = () => window.open("/clip", "_blank"); $("#quickrev").onclick = () => quickReview();
    const runs = S.runs.filter(matches);
    if (!JOB_SORTS[S.jobSort]) S.jobSort = JOB_SORTS[ls.get("jobsort")] ? ls.get("jobsort") : "match";
    const rs = runs.filter(inTab).sort(JOB_SORTS[S.jobSort][1]);
    const counts = Object.fromEntries(JOB_TABS.map(([k, , sts]) => [k, runs.filter(r => sts ? sts.includes(r.status) : r.starred).length]));
    const sources = [...new Set(S.runs.map(r => ((r.job || {}).source || "").split(":")[0]).filter(Boolean))].sort();
    const board = S.jobsLayout === "board";
    if (S.groupCo == null) S.groupCo = ls.get("groupco") !== "0";
    const grouped = S.groupCo && !board, items = grouped ? groupByCompany(rs) : rs;
    c.innerHTML = `<div class="view">
      <div class="tabsbar" role="tablist" aria-label="Job status">${JOB_TABS.filter(([k]) => MAIN_TABS.includes(k) && (counts[k] || ["ready", "new", "applied"].includes(k) || k === tab[0])).map(([k, l]) =>
        `<button role="tab" aria-selected="${k === tab[0]}" data-jt="${k}" title="${esc(JOB_TABS.find(x => x[0] === k)[3])}">${l}<span class="n">${counts[k]}</span></button>`).join("")}
        ${JOB_TABS.some(([k]) => !MAIN_TABS.includes(k) && counts[k]) || !MAIN_TABS.includes(tab[0]) ? `<label class="sr" for="jmore">More lists</label><select class="select tabmore ${MAIN_TABS.includes(tab[0]) ? "" : "on"}" id="jmore"><option value="">More…</option>${JOB_TABS.filter(([k]) => !MAIN_TABS.includes(k) && (counts[k] || k === tab[0])).map(([k, l]) =>
          `<option value="${k}" ${k === tab[0] ? "selected" : ""}>${l} (${counts[k]})</option>`).join("")}</select>` : ""}</div>
      <div class="toolbar">
        <label class="search">${I.search}<span class="sr">Search jobs</span><input class="input" id="q" placeholder="Search title, company or city" value="${esc(S.q)}"></label>
        <span class="grow"></span>
        <label class="sr" for="jobsort">Sort by</label><select class="select" id="jobsort" style="width:auto" title="Sort by">${Object.entries(JOB_SORTS).map(([k, v]) => `<option value="${k}" ${k === S.jobSort ? "selected" : ""}>Sort: ${v[0]}</option>`).join("")}</select>
        <button class="btn ${activeFilters() ? "primary" : ""}" id="fbtn" aria-expanded="${!!S.fopen}">Filters${activeFilters() ? ` · ${activeFilters()}` : ""}</button>
        <div class="seg" role="group" aria-label="Layout"><button aria-pressed="${!board}" data-lay="list">List</button><button aria-pressed="${board}" data-lay="board">Board</button></div>
      </div>
      <p class="sweeplbl" id="sweepnote" style="margin:0 0 12px">${esc(S.sweepNote)}</p>
      ${S.fopen ? `<div class="card fpanel" role="region" aria-label="Filters">
        <label>Source <select class="select" id="srcf" ><option value="">All sources</option>${sources.map(s => `<option ${S.srcFilter === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label>
        ${board ? "" : `<label class="row"><input type="checkbox" id="groupco" ${grouped ? "checked" : ""}> Group jobs by company</label>`}
        <label class="row"><input type="checkbox" id="f-remote" ${S.jf?.remote ? "checked" : ""}> Remote only</label>
        <label class="row"><input type="checkbox" id="f-full" ${S.jf?.fullDesc ? "checked" : ""}> Full description available</label>
        <label>Match at least <span class="rangeval">${S.jf?.minScore ? pct(S.jf.minScore) : "any"}</span><input type="range" id="f-score" min="0" max="0.9" step="0.05" value="${S.jf?.minScore || 0}"></label>
        <label>Salary at least <span class="rangeval">${S.jf?.minLpa ? "₹" + S.jf.minLpa + " LPA" : "any"}</span><input type="range" id="f-lpa" min="0" max="50" value="${S.jf?.minLpa || 0}"></label>
        <button class="btn sm ghost" id="f-clear">Clear filters</button>
        <p class="small muted" style="grid-column:1/-1;margin:0">These only change what you see here. To stop jobs coming in at all, use Settings › Job preferences.</p></div>` : ""}
      ${board ? `<div class="board">${COLS.map(col => { const cs = runs.filter(r => col.st.includes(r.status)).sort(JOB_SORTS[S.jobSort][1]);
          return `<section class="col ${col.hot && cs.length ? "hot" : ""}" aria-label="${col.label}"><div class="col-h"><span class="bullet" style="--c:${col.c}"></span>${col.label}<span class="n">${cs.length}</span></div>
            ${cs.slice(0, 50).map(card).join("") || '<div class="empty">Nothing here</div>'}</section>`; }).join("")}</div>`
        : `${["hidden", "low"].includes(tab[0]) ? `<p class="tabhelp">${esc(tab[3])}</p>` : ""}<div class="list">${(grouped ? items.slice(0, S.jobsShown || 40).map(companyGroup) : rs.slice(0, S.jobsShown || 40).map(row)).join("")
            || `<div class="card empty big">${tab[0] === "ready" ? EMPTY.done + "<b>Nothing waiting for you</b><span>Prepare an application from New matches, or find new jobs.</span>" : EMPTY.search + "<b>Nothing here yet</b>"}</div>`}</div>
          ${(grouped ? items : rs).length > (S.jobsShown || 40) ? `<div class="morebar"><span class="small muted">Showing ${S.jobsShown || 40} of ${(grouped ? items : rs).length}${grouped ? " companies and jobs" : ""}, ${JOB_SORTS[S.jobSort][2]}</span><button class="btn" id="morejobs">Show 40 more</button></div>` : ""}`}
    </div>`;
    $$("[data-jt]", c).forEach(b => b.onclick = () => { S.jobsTab = b.dataset.jt; S.jobsShown = 40; S.animate = true; draw(); });
    $$("[data-co]", c).forEach(h => h.onclick = () => { const k = h.dataset.co, set = S.openCos || (S.openCos = new Set()), y = scrollY;
      set.has(k) ? set.delete(k) : set.add(k); c.classList.add("noanim"); draw(); scrollTo(0, y);
      const again = $$("[data-co]", c).find(x => x.dataset.co === k); if (again) again.focus({ preventScroll: true }); });
    $("#jobsort", c).onchange = e => { S.jobSort = e.target.value; ls.set("jobsort", S.jobSort); S.jobsShown = 40; c.classList.add("noanim"); draw(); $("#jobsort", c).focus(); };
    const gc = $("#groupco", c); if (gc) gc.onchange = () => { S.groupCo = gc.checked; ls.set("groupco", gc.checked ? "1" : "0"); S.jobsShown = 40; draw(); };
    const mj = $("#morejobs", c); if (mj) mj.onclick = () => { const y = scrollY; S.jobsShown = (S.jobsShown || 40) + 40; c.classList.add("noanim"); draw(); scrollTo(0, y); };
    if ($("#jmore", c)) $("#jmore", c).onchange = e => { if (e.target.value) { S.jobsTab = e.target.value; S.animate = true; draw(); } };
    $$("[data-jt]", c).forEach(b => b.onkeydown = e => { if (["ArrowRight", "ArrowLeft"].includes(e.key)) { const all = $$("[data-jt]", c), i = all.indexOf(b) + (e.key === "ArrowRight" ? 1 : -1); all[(i + all.length) % all.length].click(); $(`[data-jt="${S.jobsTab}"]`, c).focus(); } });
    $$("[data-lay]", c).forEach(b => b.onclick = () => { S.jobsLayout = b.dataset.lay; ls.set("layout", S.jobsLayout); S.animate = true; draw(); });
    $("#fbtn", c).onclick = () => { S.fopen = !S.fopen; draw(); };
    const jf = () => (S.jf = S.jf || {});
    if ($("#f-remote", c)) {
      $("#f-remote", c).onchange = e => { jf().remote = e.target.checked; draw(); };
      $("#f-full", c).onchange = e => { jf().fullDesc = e.target.checked; draw(); };
      $("#f-score", c).onchange = e => { jf().minScore = +e.target.value; draw(); };
      $("#f-lpa", c).onchange = e => { jf().minLpa = +e.target.value; draw(); };
      $("#f-clear", c).onclick = () => { S.jf = {}; S.srcFilter = ""; draw(); };
    }
    const q = $("#q", c); q.oninput = () => { S.q = q.value; clearTimeout(S.qTimer);      // redraw once typing pauses, not on every key
      S.qTimer = setTimeout(() => { S.jobsShown = 40; c.classList.add("noanim"); draw(); const n = $("#q", c); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 160); };
    if ($("#srcf", c)) $("#srcf", c).onchange = e => { S.srcFilter = e.target.value; draw(); };
    bindCards(c);
  };
  draw();
}

// ---------------------------------------------------------------- companies (OSINT)
async function vCompanies(c) {
  c.innerHTML = `<div class="grid-co">${[1, 2, 3, 4, 5, 6].map(() => '<div class="card sk" style="height:150px"></div>').join("")}</div>`;
  const cos = await api("/companies");
  const q = (S.coq || "").toLowerCase();
  const list = cos.filter(x => !q || x.company.toLowerCase().includes(q));
  c.innerHTML = `<div class="view"><div class="toolbar"><label class="search">${I.search}<span class="sr">Search companies</span><input class="input" id="coq" placeholder="Search companies" value="${esc(S.coq || "")}"></label>
      <span class="grow"></span><span class="sweeplbl">Public, passive sources only — company websites, public DNS, Wikipedia, news and job boards. No personal data about people.</span></div>
    <div class="grid-co">${list.map((x, i) => `<button class="card co" style="--i:${Math.min(i, 24)}" data-co="${esc(x.company)}">
        <div class="row" style="flex-wrap:nowrap">${avatar(x.company, x.domain)}<div style="min-width:0;text-align:left"><b>${esc(x.company)}</b><div class="small muted">${esc(x.domain || "domain unknown")}</div></div>
          <span class="grow"></span>${x.best ? scoreBadge(x.best, "") : ""}</div>
        <div class="meta" style="margin-top:10px">${x.rating ? `<span class="chip">★ ${esc(x.rating)}</span>` : ""}<span class="chip">${x.jobs} job${x.jobs > 1 ? "s" : ""} for you</span>
          ${x.researched ? `${x.open_roles != null ? `<span class="chip info">${x.open_roles} open roles</span>` : ""}${x.security_roles ? `<span class="chip ai">${x.security_roles} in security</span>` : ""}
            ${x.dmarc ? `<span class="chip ${x.dmarc === "reject" ? "ok" : x.dmarc === "missing" || x.dmarc === "none" ? "warn" : ""}">DMARC ${esc(x.dmarc)}</span>` : ""}${x.news ? `<span class="chip">${x.news} news</span>` : ""}`
            : '<span class="chip">Not researched yet</span>'}</div></button>`).join("") || `<div class="card empty big">${EMPTY.search}<b>No companies yet</b><span>Find new jobs first.</span></div>`}</div></div>`;
  const s = $("#coq", c); s.oninput = () => { S.coq = s.value; vCompanies(c).then(() => { const n = $("#coq", c); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }); };
  $$("[data-co]", c).forEach(b => b.onclick = () => companyPanel(b.dataset.co, cos.find(x => x.company === b.dataset.co)));
}
function intelHtml(d, jobsHtml = "") {
  const id = d.identity || {}, ab = d.about || {}, se = d.security || {}, hi = d.hiring || {}, gh = d.github || {};
  const yes = (v, good = "ok") => v == null ? '<span class="chip">unknown</span>' : v ? `<span class="chip ${good}">yes</span>` : '<span class="chip warn">no</span>';
  const dm = se.dmarc ? `<span class="chip ${se.dmarc === "reject" ? "ok" : se.dmarc === "quarantine" ? "info" : "warn"}">${esc(se.dmarc)}</span>` : '<span class="chip">unknown</span>';
  return `<div class="intel">
    ${ab.summary ? `<section class="card sec"><h3>About</h3><p style="color:var(--ink-2);margin:0">${esc(ab.summary)}</p>${ab.url ? `<a class="small" href="${esc(ab.url)}" target="_blank" rel="noopener noreferrer">Wikipedia ↗</a>` : ""}</section>` : ""}
    <section class="card sec"><h3>Hiring momentum</h3>${hi.open_roles != null ? `<div class="stats3"><div><b>${hi.open_roles}</b><span>open roles</span></div><div><b>${hi.security_roles}</b><span>in security</span></div><div><b>${hi.india_or_remote}</b><span>India / remote</span></div></div>
        ${hi.security_titles && hi.security_titles.length ? `<div class="small muted" style="margin-top:10px">Security roles: ${hi.security_titles.map(esc).join(" · ")}</div>` : ""}<div class="small muted" style="margin-top:6px">From their public job board (${esc(hi.board)})</div>`
      : '<p class="muted small" style="margin:0">Their jobs aren\'t on a public Greenhouse / Lever / Ashby board we can read (many large firms use Workday).</p>'}</section>
    <section class="card sec"><h3>${I.shield.replace("<svg", '<svg width="16" height="16" style="vertical-align:-2px"')} Email &amp; web security signals</h3>
      ${se.domain ? `<p class="small muted" style="margin:0 0 8px">Passive checks on ${esc(se.domain)} — public DNS records and one homepage request. Handy talking points for a security interview.</p>
      <dl class="kv"><dt>Email provider</dt><dd>${esc(se.mail || "unknown")}</dd><dt>DMARC policy</dt><dd>${dm}</dd><dt>SPF record</dt><dd>${yes(se.spf)}</dd>
        ${se.spf_services && se.spf_services.length ? `<dt>Sends mail via</dt><dd>${se.spf_services.map(x => `<span class="chip">${esc(x)}</span>`).join(" ")}</dd>` : ""}
        <dt>HSTS on homepage</dt><dd>${yes(se.hsts)}</dd><dt>security.txt</dt><dd>${yes(se.security_txt)}</dd>
        ${se.stack && se.stack.length ? `<dt>Web stack hints</dt><dd>${se.stack.map(x => `<span class="chip ai">${esc(x)}</span>`).join(" ")}</dd>` : ""}</dl>` : '<p class="muted small" style="margin:0">Company domain not found.</p>'}</section>
    ${gh.login ? `<section class="card sec"><h3>Open source</h3><p style="margin:0"><a href="${esc(gh.url)}" target="_blank" rel="noopener noreferrer">github.com/${esc(gh.login)}</a> · ${gh.repos} public repos · ${gh.followers} followers</p></section>` : ""}
    <section class="card sec"><h3>Recent news (60 days)</h3>${(d.news || []).length ? `<ul class="news">${d.news.map(n => `<li><a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a><span class="small muted">${esc(n.source)}${n.date ? " · " + esc(ago(n.date)) : ""}</span></li>`).join("")}</ul>` : '<p class="muted small" style="margin:0">No recent coverage found.</p>'}</section>
    ${jobsHtml}
    <p class="small muted">Researched ${esc(ago(new Date(d.fetched_at * 1000).toISOString()))}. Sources: Clearbit, Wikipedia, public DNS (dns.google), company website, public job boards, GitHub, Google News.</p></div>`;
}
async function companyPanel(name, info) {
  const m = document.createElement("div"); m.className = "cmdk-scrim modal-scrim";
  m.innerHTML = `<div class="cmdk copanel" role="dialog" aria-modal="true" aria-labelledby="coh"><div class="row" style="padding:16px 20px;border-bottom:1px solid var(--line)">
      ${avatar(name, info && info.domain)}<h3 id="coh" class="grow" style="margin:0">${esc(name)}</h3><button class="btn sm" id="corf">${I.refresh}Refresh</button><button class="icon-btn" aria-label="Close" id="cox">${I.x}</button></div>
    <div class="cobody"><div class="sk" style="height:260px"></div><p class="small muted" style="text-align:center">Researching public sources… (a few seconds)</p></div></div>`;
  document.body.append(m);
  const close = () => { m.remove(); if (S.view === "companies") render(); };
  $("#cox", m).onclick = close; m.onclick = e => { if (e.target === m) close(); }; m.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  $("#cox", m).focus();
  const load_ = async force => {
    try {
      const d = await api(`/intel?company=${encodeURIComponent(name)}${force ? "&force=true" : ""}`);
      const runs = S.runs.filter(r => r.job && r.job.company === name);
      $(".cobody", m).innerHTML = intelHtml(d, runs.length ? `<section class="card sec"><h3>Your jobs here</h3><div class="list">${runs.map(row).join("")}</div></section>` : "");
      bindCards($(".cobody", m));
      $$("[data-open]", m).forEach(el => el.addEventListener("click", () => m.remove()));
    } catch (e) { $(".cobody", m).innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  };
  $("#corf", m).onclick = () => { $(".cobody", m).innerHTML = '<div class="sk" style="height:260px"></div>'; load_(true); };
  load_(false);
}

// ---------------------------------------------------------------- applications tracker
async function vApps(c) {
  const all = S.runs.filter(r => ["submitted", "approved", "submitting", "interview", "offer", "closed", "rejected", "needs_manual"].includes(r.status));
  const f = { active: r => ["submitted", "approved", "submitting", "needs_manual"].includes(r.status), interviews: r => ["interview", "offer"].includes(r.status),
              closed: r => ["closed", "rejected"].includes(r.status), followup: r => r.follow_up_due, all: () => true };
  const rs = all.filter(f[S.appsFilter]).sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  const stage = r => r.status === "interview" ? 3 : r.emails ? 2 : ["closed", "rejected"].includes(r.status) ? -1 : 1;
  c.innerHTML = `<div class="view"><div class="toolbar"><div class="seg" role="group" aria-label="Filter">${[["active", "Active"], ["followup", "Follow-up due"], ["interviews", "Interviews"], ["closed", "Closed"], ["all", "All"]]
      .map(([k, l]) => `<button aria-pressed="${S.appsFilter === k}" data-f="${k}">${l} <span class="muted">${all.filter(f[k]).length}</span></button>`).join("")}</div>
      <span class="grow"></span><span class="sweeplbl">Includes applications found in your Gmail confirmations.</span>
      <button class="btn" id="csv">${I.ext}Export CSV</button></div>
    <div class="list">${rs.map((r, i) => { const j = r.job || {}, s = stage(r);
      return `<div class="card li clickable" style="--i:${i}" data-open="${esc(r.id)}">${avatar(j.company, r.domain)}
        <div style="min-width:0"><h3>${esc(j.title)} <span class="muted" style="font-weight:400">· ${esc(j.company)}</span></h3>
          <div class="sub row" style="gap:6px;margin-top:4px">${r.channel ? `<span class="chip ai">${esc(r.channel === "external" ? "applied elsewhere" : "via " + r.channel)}</span>` : ""}
            <span>${r.channel === "external" ? "Applied " + esc(ago(r.created_at)) : esc(ago(r.updated_at))}</span>${r.emails ? `<span class="chip info">${r.emails} email${r.emails > 1 ? "s" : ""}</span>` : ""}
            ${r.follow_up_due ? `<span class="chip warn">Follow up — ${r.days_since_update}d no reply</span>` : ""}${r.status === "needs_manual" ? '<span class="chip warn">Submit via form</span>' : ""}</div></div>
        <div class="row"><div class="timeline" title="Applied → Response → Interview">${[1, 2, 3].map(n => `<i class="${s === -1 ? (n === 1 ? "on" : "bad") : n <= s ? "on" : ""}"></i>`).join("")}</div>
          <span class="chip ${r.status === "interview" ? "ok" : ["closed", "rejected"].includes(r.status) ? "miss" : ""}">${esc(st(r.status))}</span>
          ${r.status === "submitted" && j.apply_email ? `<button class="btn sm" data-fu="${esc(r.id)}">${I.mail}Follow up</button>` : ""}</div>
        <div data-fubox="${esc(r.id)}" style="grid-column:1/-1"></div></div>`; }).join("")
      || `<div class="card empty big">${EMPTY.cards}<b>No applications here</b><span>Approved applications and ones found in your Gmail show up here.</span></div>`}</div></div>`;
  $$("[data-f]", c).forEach(b => b.onclick = () => { S.appsFilter = b.dataset.f; S.animate = true; vApps(c); });
  $$("[data-fu]", c).forEach(b => b.onclick = e => { e.stopPropagation(); followComposer(b.dataset.fu, $(`[data-fubox="${b.dataset.fu}"]`, c)); });
  $("#csv", c).onclick = () => {
    const q = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [["Company", "Role", "Status", "Channel", "Match", "Salary", "Applied/updated", "Emails", "Follow-up due", "Link"].map(q).join(",")]
      .concat(all.map(r => [r.job?.company, r.job?.title, st(r.status), r.channel, r.match_score != null ? pct(r.match_score) : "", r.salary?.label,
        new Date(r.updated_at).toLocaleDateString(), r.emails, r.follow_up_due ? "yes" : "", r.job?.url].map(q).join(",")));
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    a.download = `applications-${new Date().toISOString().slice(0, 10)}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast(`Exported ${all.length} applications`);
  };
  bindCards(c);
}

// ---------------------------------------------------------------- inbox
const _when = m => new Date(m.received_at).getTime() || 0, _newest = (a, b) => _when(b) - _when(a);
const _needs = m => ["interview_request", "screening_questions"].includes(m.label) && !m.replied_at ? 0 : 1;      // waiting on you
const _kind = m => ["interview_request", "screening_questions", "auto_acknowledgement", "rejection", "other"].indexOf(m.label || "other");
const MAIL_SORTS = {
  action: ["Needs a reply first", (a, b) => _needs(a) - _needs(b) || _newest(a, b)],
  newest: ["Newest", _newest],
  oldest: ["Oldest", (a, b) => _when(a) - _when(b)],
  company: ["Company A–Z", (a, b) => _txt(a.company || a.sender, b.company || b.sender) || _newest(a, b)],
  type: ["Type", (a, b) => _kind(a) - _kind(b) || _newest(a, b)],
};
async function vInbox(c) {
  const labels = [["all", "All"], ["interview_request", "Interviews"], ["screening_questions", "Screening"], ["rejection", "Rejections"], ["auto_acknowledgement", "Confirmations"]];
  if (!MAIL_SORTS[S.mailSort]) S.mailSort = MAIL_SORTS[ls.get("mailsort")] ? ls.get("mailsort") : "action";
  const ms = S.emails.filter(m => S.mailFilter === "all" || m.label === S.mailFilter).sort(MAIL_SORTS[S.mailSort][1]);
  const runName = id => { const r = S.runs.find(x => x.id === id); return r && r.job ? `${r.job.title} · ${r.job.company}` : ""; };
  c.innerHTML = `<div class="view"><div class="toolbar"><div class="seg">${labels.map(([k, l]) => `<button aria-pressed="${S.mailFilter === k}" data-l="${k}">${l} <span class="muted">${k === "all" ? S.emails.length : S.emails.filter(m => m.label === k).length}</span></button>`).join("")}</div>
      <label class="sr" for="mailsort">Sort by</label><select class="select" id="mailsort" style="width:auto" title="Sort by">${Object.entries(MAIL_SORTS).map(([k, v]) => `<option value="${k}" ${k === S.mailSort ? "selected" : ""}>Sort: ${v[0]}</option>`).join("")}</select>
      <span class="grow"></span><span class="sweeplbl">Only job-related mail is read. Newsletters are ignored and never stored.</span>
      <button class="btn" id="poll"><span class="spin">${I.refresh}</span>Check inbox now</button></div>
    <div class="list">${ms.map((m, i) => `<div class="card li mail" style="--i:${i};grid-template-columns:auto 1fr" data-mail="${esc(m.id)}">
        ${avatar(m.company || m.sender_name || m.sender)}
        <div style="min-width:0"><div class="row" style="gap:8px"><span class="chip lbl-${esc(m.label)}">${esc(MAIL_LABEL[m.label] || "Message")}</span>
            <b>${esc(m.company || m.sender)}</b><span class="muted small">${m.sender_name && m.sender_name !== m.company ? esc(m.sender_name) + " · " : ""}${esc(ago(m.received_at))}</span></div>
          <h3 style="margin-top:6px">${esc(m.subject)}</h3>
          ${m.action ? `<div class="small" style="color:var(--amber);font-weight:600;margin-top:4px">→ ${esc(m.action)}</div>` : ""}
          <div class="body">${esc(cleanMail(m.body))}</div>
          <div class="row" style="margin-top:8px;gap:6px">
            ${m.calendar_links.map(l => `<a class="btn sm success" href="${esc(l)}" target="_blank" rel="noopener noreferrer">${I.cal}${esc(new URL(l).hostname.replace("www.", ""))}</a>`).join("")}
            ${m.proposed_slots.map(s => `<span class="chip ok">${I.cal.replace("<svg", '<svg width="12" height="12"')} ${esc(s)}</span>`).join("")}
            ${m.run_id ? `<button class="btn sm ghost" data-open="${esc(m.run_id)}">View application: ${esc(runName(m.run_id))}</button>` : ""}
            ${m.label === "interview_request" ? `<button class="btn sm primary" data-addiv="${esc(m.id)}">${I.cal}Add to interviews</button>` : ""}
            ${m.id.startsWith("gmail:") ? (m.replied_at ? `<span class="chip ok">${I.reply.replace("<svg", '<svg width="12" height="12"')} Replied ${esc(ago(m.replied_at))}</span>`
              : `<button class="btn sm" data-draft="${esc(m.id)}">${I.sparkle}Draft reply</button>`) : ""}
          </div><div data-composer="${esc(m.id)}"></div></div></div>`).join("")
      || `<div class="card empty big">${EMPTY.inbox}<b>No recruiter mail yet</b><span>Replies, interview invites and confirmations appear here automatically.</span></div>`}</div></div>`;
  $$("[data-l]", c).forEach(b => b.onclick = () => { S.mailFilter = b.dataset.l; S.animate = true; vInbox(c); });
  $("#mailsort", c).onchange = e => { S.mailSort = e.target.value; ls.set("mailsort", S.mailSort); S.animate = false; c.classList.add("noanim"); vInbox(c).then(() => $("#mailsort", c).focus()); };
  $$("[data-mail]", c).forEach(el => el.onclick = e => { if (!e.target.closest("a,button")) el.classList.toggle("open"); });
  bindCards(c);
  $$("[data-addiv]", c).forEach(b => b.onclick = async e => { e.stopPropagation(); try { interviewForm({}, await api(`/inbox/${encodeURIComponent(b.dataset.addiv)}/interview-suggestion`)); } catch (x) { toast(x.message); } });
  $$("[data-draft]", c).forEach(b => b.onclick = e => { e.stopPropagation(); composer(b.dataset.draft, $(`[data-composer="${CSS.escape(b.dataset.draft)}"]`, c)); });
  $("#poll", c).onclick = async e => {
    const b = e.currentTarget; b.classList.add("busy"); b.disabled = true;
    try { const r = await api("/inbox/poll", { method: "POST" });
      toast(r.ok ? `Checked ${r.seen} new · ${r.kept} job-related${r.imported ? ` · ${r.imported} applications imported` : ""}` : r.error); }
    catch (x) { toast(x.message); }
    S.emails = await api("/inbox"); S.animate = true; render();
  };
}

// ---------------------------------------------------------------- insights
async function vInsights(c) {
  c.innerHTML = `<div class="insights">${[1, 2, 3, 4].map(() => '<div class="card viz-card"><div class="sk" style="height:220px"></div></div>').join("")}</div>`;
  const d = await api("/insights");
  const f = d.funnel, applied = f[2].n, heard = f[3].n, gaps = d.skill_demand.filter(s => !s.have);
  const hero = [[f[0].n, "jobs discovered"], [f[1].n, "applications prepared"], [applied, "applications sent"],
                [applied ? Math.round(heard / applied * 100) + "%" : "–", "response rate"], [f[4].n, "interviews"]];
  const src = d.by_source.slice(0, 6).concat(d.by_source.length > 6 ? [["other", d.by_source.slice(6).reduce((a, x) => a + x[1], 0)]] : []);
  const days = d.timeline.map(t => new Date(t.day + "T00:00").toLocaleDateString([], { day: "numeric", month: "short" }));
  const hl = ["0–9", "10–19", "20–29", "30–39", "40–49", "50–59", "60–69", "70–79", "80–89", "90–100"];
  c.innerHTML = `<div class="view">
    <div class="hero">${hero.map(([n, l]) => `<div class="card"><b>${esc(n)}</b><span>${esc(l)}</span></div>`).join("")}</div>
    <div class="insights">
      ${Charts.card("v-skill", "Skills employers ask for", `Mentions across ${d.totals.analysed} jobs with full descriptions — blue you have, orange you don't list`,
        Charts.hbars(d.skill_demand.map(s => ({ label: skillName(s.skill), value: s.jobs, color: s.have ? Charts.S(1) : Charts.S(2), note: s.have ? "in your profile" : "not in your profile" })),
          { unit: " jobs", legendItems: [["In your profile", Charts.S(1)], ["Gap — not in your profile", Charts.S(2)]],
            emptyMsg: "Needs jobs with full descriptions — company career sites and Naukri invites provide them. Click Refresh jobs." })
        + (gaps.length ? `<div class="gapnote"><b>Biggest gaps:</b> ${gaps.slice(0, 4).map(g => esc(skillName(g.skill))).join(", ")}. If you genuinely have these, add them to your profile — matches and tailoring update instantly. The fact checker never lets tailoring claim them otherwise.</div>` : ""),
        Charts.table(["Skill", "Jobs asking", "In your profile"], d.skill_demand.map(s => [skillName(s.skill), s.jobs, s.have ? "yes" : "no"])))}
      ${Charts.card("v-funnel", "Application funnel", "From discovery to interview", Charts.funnel(f), Charts.table(["Stage", "Count"], f.map(x => [x.stage, x.n])))}
      ${Charts.card("v-time", "Activity, last 3 weeks", "Jobs discovered and applications sent per day",
        Charts.columns(days, [{ name: "Discovered", color: Charts.S(1), values: d.timeline.map(t => t.discovered) }, { name: "Applied", color: Charts.S(2), values: d.timeline.map(t => t.applied) }], { labelEvery: 4 }),
        Charts.table(["Day", "Discovered", "Applied"], d.timeline.map((t, i) => [days[i], t.discovered, t.applied])))}
      ${Charts.card("v-src", "Where jobs come from", "Share of all discovered jobs by source",
        Charts.donut(src.map(([l, n], i) => ({ label: l, value: n, color: Charts.S(i + 1) })), { center: String(d.totals.jobs) }),
        Charts.table(["Source", "Jobs"], src))}
      ${Charts.card("v-score", "Match score distribution", "How well discovered jobs fit your profile",
        Charts.columns(hl, [{ name: "Jobs", color: Charts.S(1), values: d.score_hist }], { showValues: true }),
        Charts.table(["Score %", "Jobs"], hl.map((h, i) => [h, d.score_hist[i]])))}
      ${Charts.card("v-sal", "Stated salaries (₹ LPA)", `${d.totals.salary_known} listings state INR pay — mostly Glassdoor estimates and Naukri`,
        Charts.columns(d.salary_lpa.map(s => s.band), [{ name: "Jobs", color: Charts.S(1), values: d.salary_lpa.map(s => s.n) }], { showValues: true }),
        Charts.table(["LPA band", "Jobs"], d.salary_lpa.map(s => [s.band, s.n])))}
      ${await learningCard(gaps.map(g => g.skill))}
      ${salaryCard()}
    </div></div>`;
  Charts.wire(c); bindLearning(c); bindSalary(c);
}

async function followComposer(rid, box) {
  if (box.innerHTML) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="composer" onclick="event.stopPropagation()"><div class="row"><b class="grow">Follow-up email</b><span class="small muted" id="fuhow"></span></div>
    <textarea class="textarea" style="margin-top:8px" aria-label="Follow-up message">Drafting…</textarea>
    <div class="row" style="margin-top:8px"><span class="small muted grow" id="futo"></span><button class="btn sm" data-re>Redraft</button><button class="btn sm success" data-send>${I.send}Send follow-up</button></div></div>`;
  const ta = $("textarea", box);
  const draft = async () => { ta.value = "Drafting…"; ta.disabled = true;
    try { const r = await api(`/runs/${rid}/followup/draft`, { method: "POST" }); ta.value = r.body; $("#futo", box).textContent = "To: " + r.to; $("#fuhow", box).textContent = r.method === "template" ? "template" : "by " + r.method; }
    catch (e) { toast(e.message); } ta.disabled = false; ta.focus(); };
  $("[data-re]", box).onclick = draft;
  $("[data-send]", box).onclick = async e => { const b = e.currentTarget; b.disabled = true;
    try { const r = await api(`/runs/${rid}/followup/send`, { method: "POST", body: { body: ta.value } }); celebrate(r.dry_run ? "Follow-up approved (practice mode)" : "Follow-up sent"); setTimeout(() => render(), 1300); }
    catch (x) { toast(x.message, 5000); b.disabled = false; } };
  draft();
}

async function composer(mid, box) {
  if (box.innerHTML) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="composer" onclick="event.stopPropagation()"><div class="row"><b class="grow">${I.sparkle.replace("<svg", '<svg width="14" height="14"')} Reply draft</b><span class="small muted" id="how"></span></div>
    <textarea class="textarea" style="margin-top:8px" aria-label="Reply">Drafting…</textarea>
    <div class="row" style="margin-top:8px"><input class="input grow" style="flex:1;min-width:180px" placeholder="Tell the AI what to change, e.g. 'propose Thursday afternoon'" aria-label="Instruction">
      <button class="btn sm" data-re>Redraft</button><button class="btn sm success" data-send>${I.send}Send reply</button></div>
    <div class="hint" style="margin-top:6px">Replaces nothing automatically — fill any <b>[placeholders]</b>; you press Send. Goes out in the same Gmail thread.</div></div>`;
  const ta = $("textarea", box), note = $("input", box);
  const draft = async () => { ta.value = "Drafting…"; ta.disabled = true;
    try { const r = await api(`/inbox/${encodeURIComponent(mid)}/draft`, { method: "POST", body: { note: note.value } }); ta.value = r.body; $("#how", box).textContent = r.method === "template" ? "template" : "by " + r.method; }
    catch (e) { ta.value = ""; toast(e.message); } ta.disabled = false; ta.focus(); };
  $("[data-re]", box).onclick = draft;
  $("[data-send]", box).onclick = async e => {
    if (/\[your/i.test(ta.value)) return toast("Fill in the [placeholders] first");
    const b = e.currentTarget; b.disabled = true;
    try { const r = await api(`/inbox/${encodeURIComponent(mid)}/reply`, { method: "POST", body: { body: ta.value } });
      celebrate(r.dry_run ? "Reply approved (dry-run)" : "Reply sent"); S.emails = await api("/inbox"); setTimeout(() => render(), 1300); }
    catch (x) { toast(x.message, 5000); b.disabled = false; }
  };
  draft();
}

// ---------------------------------------------------------------- settings
function tagsField(key, label, hint, placeholder, validate) {
  return `<div class="field"><div class="lab">${label}</div><div class="tags" data-tags="${key}">
    ${(S.form[key] || []).map((t, i) => `<span class="chip">${esc(t)}<button aria-label="Remove ${esc(t)}" data-rm="${i}">×</button></span>`).join("")}
    <input placeholder="${esc(placeholder)}" aria-label="${esc(label)}"></div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
}
const TONES = [["conservative", "Conservative", "Formal and understated"], ["technical", "Technical", "Systems, tools, mechanisms"],
               ["impact", "Startup impact", "Outcomes and metrics first"], ["narrative", "Narrative", "Warm first-person story"]];
const SET_TABS = [["profile", "Profile & resume"], ["prefs", "Job preferences"], ["accounts", "Gmail & sending"], ["a11y", "Accessibility"], ["activity", "Activity log"]];
async function vSettingsHub(c) {
  c.innerHTML = `<div class="view"><div class="tabsbar" role="tablist" aria-label="Settings sections">${SET_TABS.map(([k, l]) =>
    `<button role="tab" aria-selected="${S.setTab === k}" data-st="${k}">${l}</button>`).join("")}</div><div id="setbody"></div></div>`;
  $$("[data-st]", c).forEach(b => b.onclick = () => { if ((S.dirty || S.pdirty) && !confirm("Discard unsaved changes?")) return; S.dirty = S.pdirty = false; S.pdraft = null; S.setTab = b.dataset.st; S.animate = true; vSettingsHub(c); });
  const body = $("#setbody", c);
  await ({ profile: vProfile, prefs: vSettings, accounts: vSettings, a11y: vA11y, activity: vActivity }[S.setTab] || vProfile)(body);
}
function vA11y(c) {
  const a = A11Y.get();
  const notifOk = "Notification" in window;
  c.innerHTML = `<div class="settings">
    <section class="card sec"><h3>Appearance</h3><p>Saved in this browser.</p>
      <div class="field"><div class="lab" id="thl">Theme</div><div class="seg" role="group" aria-labelledby="thl">${Object.entries(THEMES).map(([k, l]) => `<button aria-pressed="${curTheme() === k}" data-th="${k}">${l}</button>`).join("")}</div>
        <div class="hint">Futuristic: dark glass with neon accents. All themes meet WCAG AA text contrast.</div></div></section>
    <section class="card sec"><h3>Reading comfort</h3><p>Saved in this browser.</p>
      <div class="field"><div class="lab" id="tsl">Text size</div><div class="seg" role="group" aria-labelledby="tsl">${[["normal", "Normal"], ["large", "Large"], ["xl", "Extra large"]].map(([k, l]) => `<button aria-pressed="${(a.text || "normal") === k}" data-ts="${k}">${l}</button>`).join("")}</div></div>
      ${[["contrast", "High contrast", "Darker text, stronger borders and focus outlines."], ["motion", "Reduce motion", "Turns off animations, confetti and card movement."]].map(([k, t, d]) =>
        `<div class="field row" style="justify-content:space-between"><div><b>${t}</b><div class="hint" style="margin:0">${d}</div></div><button class="switch" role="switch" aria-label="${t}" data-a="${k}" aria-checked="${!!a[k]}"><span class="track"></span></button></div>`).join("")}
    </section>
    <section class="card sec"><h3>Notifications</h3><p>Get a desktop notification when an application is ready or a recruiter replies (while this tab is open).</p>
      <div class="field row" style="justify-content:space-between"><div><b>Desktop notifications</b><div class="hint" style="margin:0">${notifOk ? (Notification.permission === "denied" ? "Blocked in your browser settings." : "") : "Not supported in this browser."}</div></div>
        <button class="switch" role="switch" aria-label="Desktop notifications" id="notif" aria-checked="${!!a.notify && notifOk && Notification.permission === "granted"}" ${notifOk ? "" : "disabled"}><span class="track"></span></button></div></section>
    <section class="card sec"><h3>Keyboard</h3><p>Everything works without a mouse.</p>${shortcutList()}</section>
  </div>`;
  $$("[data-ts]", c).forEach(b => b.onclick = () => { A11Y.set("text", b.dataset.ts); vA11y(c); });
  $$("[data-th]", c).forEach(b => b.onclick = () => { setTheme(b.dataset.th); vA11y(c); });
  $$("[data-a]", c).forEach(b => b.onclick = () => { A11Y.set(b.dataset.a, !A11Y.get()[b.dataset.a]); vA11y(c); });
  const n = $("#notif", c);
  if (n) n.onclick = async () => {
    if (A11Y.get().notify) { A11Y.set("notify", false); return vA11y(c); }
    const p = await Notification.requestPermission();
    A11Y.set("notify", p === "granted"); toast(p === "granted" ? "Notifications on" : "Your browser blocked notifications"); vA11y(c);
  };
}
const KEYS = [["⌘K / Ctrl+K", "Search jobs and actions"], ["1 – 9", "Go to Dashboard, Jobs, Applications, Interviews, Outreach, Inbox, Companies, Insights, Settings"], ["/", "Search jobs"],
              ["n", "Find new jobs"], ["Enter", "Open the focused job"], ["Esc", "Close a panel"], ["?", "Show this list"]];
function shortcutList() { return `<dl class="keys">${KEYS.map(([k, d]) => `<dt><span class="kbd">${esc(k)}</span></dt><dd>${esc(d)}</dd>`).join("")}</dl>`; }
function shortcuts() {
  if ($(".modal-scrim")) return;
  const m = document.createElement("div"); m.className = "cmdk-scrim modal-scrim";
  m.innerHTML = `<div class="cmdk" role="dialog" aria-modal="true" aria-labelledby="kt" style="padding:18px 22px"><div class="row"><h3 id="kt" class="grow" style="margin:0">Keyboard shortcuts</h3><button class="icon-btn" aria-label="Close">${I.x}</button></div>${shortcutList()}</div>`;
  document.body.append(m); const close = () => m.remove();
  $("button", m).onclick = close; m.onclick = e => { if (e.target === m) close(); }; $("button", m).focus();
  m.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
}

async function vSettings(c, part = S.setTab) {
  if (!S.form || !S.dirty) S.form = structuredClone(S.settings);
  const f = S.form, ap = f.autopilot;
  const mark = () => { S.dirty = JSON.stringify(S.form) !== JSON.stringify(S.settings); $(".savebar", c).classList.toggle("on", S.dirty); };
  let gm = S.gmail;
  if (!gm) { try { gm = S.gmail = await api("/gmail/status"); } catch { gm = { connected: false, address: "", has_client: false }; } }
  c.innerHTML = `<div class="view"><div class="settings">
    <section class="card sec" data-part="accounts"><h3>Gmail account</h3><p>Used to send applications, read recruiter replies and job-alert emails. Permissions: send + read-only.</p>
      <div class="acct"><div class="gm">${I.mail}</div><div class="grow" style="min-width:0"><b>${gm.connected ? esc(gm.address || "Connected") : "Not connected"}</b>
        <div class="small muted">${gm.connected ? "Sending and inbox reading active" : gm.has_client ? "Ready to connect" : "Add your Google OAuth client first"}</div></div>
        <span class="dot ${gm.connected ? "live" : "off"}"></span></div>
      <div class="row" style="margin-top:12px">${gm.has_client ? `<button class="btn primary" id="gconnect">${gm.connected ? "Switch account" : "Connect Gmail"}</button>` : ""}
        ${gm.connected ? '<button class="btn danger" id="gdisc">Disconnect</button>' : ""}</div>
      ${gm.has_client ? "" : `<div class="field"><label class="small muted" for="gcid">OAuth client ID (Desktop app)</label><input class="input" id="gcid" placeholder="….apps.googleusercontent.com">
        <label class="small muted" for="gcs" style="display:block;margin-top:8px">Client secret</label><input class="input" id="gcs" type="password">
        <button class="btn" id="gsave" style="margin-top:8px">Save client</button>
        <div class="hint">Google Cloud Console → APIs &amp; Services → Credentials → Create OAuth client (Desktop app), and enable the Gmail API. Stored only in your local <code>.env</code>.</div></div>`}
      <div class="hint">Switching accounts clears the previous inbox's cached emails. Applications you've tracked are kept.</div>
    </section>
    <section class="card sec" data-part="prefs"><h3>Which jobs to look for</h3><p>Saving re-checks every job already in your list — jobs that no longer fit move to “Hidden by filters” (nothing is deleted).</p>
      ${tagsField("target_titles", "Job titles should include", "A job is kept if its title contains any of these words, e.g. security, detection.", "Add a keyword and press Enter")}
      ${tagsField("target_locations", "Locations", "Remote roles you can do from here, plus on-site/hybrid roles in these places.", "e.g. Bengaluru, India")}
      <div class="field"><div class="lab">Work modes</div><div class="seg">${["remote", "hybrid", "onsite"].map(m => `<button data-mode="${m}" aria-pressed="${f.work_modes.includes(m)}">${m[0].toUpperCase() + m.slice(1)}</button>`).join("")}</div></div>
      <div class="field"><label for="ms">Minimum salary <span class="rangeval" id="msv">${f.min_salary_lpa ? "₹" + f.min_salary_lpa + " LPA" : "off"}</span></label><input type="range" id="ms" min="0" max="60" step="1" value="${f.min_salary_lpa || 0}">
        <div class="hint">Applies to jobs already in your list as soon as you save. Only listings that state INR pay (Glassdoor estimates, Naukri) can be filtered; jobs without pay info are kept.</div></div>
      ${tagsField("exclude_companies", "Never apply to these companies", "", "Company name")}
      ${tagsField("exclude_keywords", "Skip jobs mentioning", "", "e.g. clearance required")}
    </section>
    <section class="card sec" data-part="prefs"><h3>Matching &amp; writing</h3><p>How picky to be, and how many jobs the AI prepares automatically.</p>
      <div class="field"><label for="mm">Minimum match score <span class="rangeval" id="mmv">${pct(f.min_match)}</span></label><input type="range" id="mm" min="0" max="0.8" step="0.05" value="${f.min_match}">
        <div class="hint">Applies immediately: jobs below this move to “Low matches”.</div></div>
      <div class="field"><label for="wg">Weekly application goal <span class="rangeval" id="wgv">${f.weekly_goal}</span></label><input type="range" id="wg" min="1" max="40" value="${f.weekly_goal}">
        <div class="hint">Shown on your dashboard with a streak for every week you hit it.</div></div>
      <div class="field"><label for="oc">Recruiter emails per day, at most <span class="rangeval" id="ocv">${f.outreach_daily_cap}</span></label><input type="range" id="oc" min="1" max="30" value="${f.outreach_daily_cap}">
        <div class="hint">A cap on Outreach keeps you a polite sender. Around 10 a day is plenty.</div></div>
      <div class="field"><label for="ao">Prepare outreach drafts for the best <span class="rangeval" id="aov">${f.auto_outreach}</span> new matches after each refresh</label><input type="range" id="ao" min="0" max="20" value="${f.auto_outreach}">
        <div class="hint">Drafts only — nothing is sent until you approve it. Set to 0 to turn off.</div></div>
      <div class="field"><label for="tt">Automatically prepare the best <span class="rangeval" id="ttv">${f.auto_tailor_top}</span> matches after each search</label><input type="range" id="tt" min="0" max="30" step="1" value="${f.auto_tailor_top}">
        <div class="hint">The local model takes ~1 minute per job. Others wait in Discovered with a Tailor button.</div></div>
      <div class="field"><div class="lab">Writing style for resumes and cover letters</div><div class="hint" style="margin:-2px 0 8px">Used for applications prepared from now on; use “Regenerate” on a ready one to rewrite it in the new style.</div><div class="tone">${TONES.map(([k, t, d]) => `<button data-tone="${k}" aria-pressed="${f.tone === k}"><b>${t}</b><span>${d}</span></button>`).join("")}</div></div>
    </section>
    <section class="card sec" data-part="prefs"><h3>Where to look</h3><p>Where jobs come from. LinkedIn, Naukri and Glassdoor arrive through the alert emails you already get — never by scraping. Changes here apply from your next search.</p>
      ${[["feeds", "Remote job boards", "Remotive, RemoteOK, We Work Remotely"], ["companies", "Company career sites", "Greenhouse, Lever and Ashby job boards of your watchlist"], ["gmail_alerts", "Job-alert emails", "Glassdoor, Naukri, LinkedIn alerts in your Gmail"]]
        .map(([k, t, d]) => `<div class="field row" style="justify-content:space-between"><div><b>${t}</b><div class="hint" style="margin:0">${d}</div></div><button class="switch" role="switch" data-src="${k}" aria-checked="${f.sources[k] !== false}"><span class="track"></span></button></div>`).join("")}
      <div class="field"><label for="colink">Add a company from its careers page link</label><div class="row" style="flex-wrap:nowrap"><input class="input" id="colink" placeholder="e.g. https://boards.greenhouse.io/rubrik or jobs.lever.co/meesho"><button class="btn" id="coadd">Add</button></div>
        <div class="hint">Works for Greenhouse, Lever, Ashby and SmartRecruiters career sites.</div></div>
      <div class="field"><label for="ar">Research the best <span class="rangeval" id="arv">${f.auto_research}</span> short listings after each search</label><input type="range" id="ar" min="0" max="40" value="${f.auto_research}">
        <div class="hint">Alert emails often contain only a job title. We look for the same role on the company's own careers site to get the full description (and a direct application link).</div></div>
      ${tagsField("watch_companies", "Company watchlist", 'Format <code>greenhouse:slug</code>, <code>lever:slug</code> or <code>ashby:slug</code> — the slug is in the company\'s careers URL, e.g. boards.greenhouse.io/<b>rubrik</b>.', "greenhouse:company", v => /^(greenhouse|lever|ashby):[a-z0-9-]+$/.test(v))}
    </section>
    ${bookmarkletSection()}
    ${extensionSection()}
    <section class="card sec" data-part="accounts"><h3>Daily summary email</h3><p>A short morning email to yourself: interviews coming up, applications waiting for you, recruiter replies and strong new matches.</p>
      <div class="field"><label for="dh">Send it at</label><select class="select" id="dh">${[[-1, "Off"], ...[6, 7, 8, 9, 10, 12, 18, 20].map(h => [h, new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" })])].map(([v, l]) => `<option value="${v}" ${+f.digest_hour === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <div class="hint">Sent from and to your connected Gmail. Nothing is sent in practice mode.</div></div>
      <button class="btn" id="dgnow">Preview today's summary</button></section>
    <section class="card sec" data-part="accounts"><h3>Your data</h3><p>Everything you've built here — profile, jobs, applications, emails, interviews, offers and notes — as one file you can keep.</p>
      <button class="btn" id="export">${I.ext}Download my data</button></section>
    <section class="card sec" data-part="accounts"><h3>Automation</h3><p>What runs on its own. Every outbound application still passes the fact checker.</p>
      <div class="field"><label for="sh">Search for new jobs automatically</label><select class="select" id="sh">${[[0, "Only when I click Find new jobs"], [3, "Every 3 hours"], [6, "Every 6 hours"], [12, "Every 12 hours"], [24, "Daily"]].map(([v, l]) => `<option value="${v}" ${+f.sweep_hours === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div class="field"><label for="fu">Flag applications for follow-up after <span class="rangeval" id="fuv">${f.follow_up_days}</span> days without a reply</label><input type="range" id="fu" min="3" max="30" value="${f.follow_up_days}"></div>
      <div class="field row" style="justify-content:space-between"><div><b>Autopilot</b><div class="hint" style="margin:0">Send email applications without asking, only above the threshold below.</div></div>
        <button class="switch violet" role="switch" id="apon" aria-checked="${ap.enabled}"><span class="track"></span></button></div>
      <div class="field"><label for="aps">Autopilot only when match ≥ <span class="rangeval" id="apsv">${pct(ap.min_score)}</span></label><input type="range" id="aps" min="0.5" max="1" step="0.05" value="${ap.min_score}"></div>
      <div class="field"><label for="apc">At most <span class="rangeval" id="apcv">${ap.daily_cap}</span> automatic applications per day</label><input type="range" id="apc" min="1" max="20" value="${ap.daily_cap}"></div>
      <div class="callout">Autopilot never fills web forms and never sends while the app is in dry-run. Keep it off until you've reviewed a few applications yourself.</div>
      <div class="field"><button class="btn" id="testsend">${I.mail}Send a test application to myself</button></div>
    </section>
  </div>
  <div class="savebar" role="region" aria-label="Unsaved changes"><b>Unsaved changes</b><span class="grow"></span><button class="btn ghost" id="discard" style="background:transparent;color:inherit">Discard</button><button class="btn" id="save">Save changes</button></div></div>`;

  $$("[data-part]", c).forEach(s => s.hidden = s.dataset.part !== part);
  // tag inputs
  $$("[data-tags]", c).forEach(box => {
    const key = box.dataset.tags, inp = $("input", box);
    const validate = key === "watch_companies" ? v => /^(greenhouse|lever|ashby):[a-z0-9-]+$/.test(v) : () => true;
    const redraw = () => { S.animate = false; vSettings(c, part).then(() => $(`[data-tags="${key}"] input`, c).focus()); };
    inp.onkeydown = e => {
      if ((e.key === "Enter" || e.key === ",") && inp.value.trim()) {
        e.preventDefault(); const v = inp.value.trim().replace(/,$/, "");
        if (!validate(v)) { toast("Use greenhouse:slug, lever:slug or ashby:slug"); return; }
        if (!(f[key] || []).includes(v)) f[key] = [...(f[key] || []), v]; mark(); redraw();
      } else if (e.key === "Backspace" && !inp.value && (f[key] || []).length) { f[key] = f[key].slice(0, -1); mark(); redraw(); }
    };
    $$("[data-rm]", box).forEach(b => b.onclick = () => { f[key].splice(+b.dataset.rm, 1); mark(); redraw(); });
    box.onclick = e => { if (e.target === box) inp.focus(); };
  });
  $$("[data-mode]", c).forEach(b => b.onclick = () => {
    const m = b.dataset.mode, on = f.work_modes.includes(m);
    if (on && f.work_modes.length === 1) return toast("Keep at least one work mode");
    f.work_modes = on ? f.work_modes.filter(x => x !== m) : [...f.work_modes, m]; b.setAttribute("aria-pressed", String(!on)); mark();
  });
  $$("[data-tone]", c).forEach(b => b.onclick = () => { f.tone = b.dataset.tone; $$("[data-tone]", c).forEach(x => x.setAttribute("aria-pressed", String(x === b))); mark(); });
  $$("[data-src]", c).forEach(b => b.onclick = () => { const k = b.dataset.src; f.sources[k] = f.sources[k] === false; b.setAttribute("aria-checked", String(f.sources[k])); mark(); });
  const rng = (id, key, fmt, obj = f) => { const el = $("#" + id, c); el.oninput = () => { obj[key] = +el.value; $("#" + id + "v", c).textContent = fmt(+el.value); mark(); }; };
  rng("wg", "weekly_goal", String); rng("oc", "outreach_daily_cap", String); rng("ao", "auto_outreach", v => v || "off"); rng("mm", "min_match", pct); rng("ar", "auto_research", String); rng("ms", "min_salary_lpa", v => v ? `₹${v} LPA` : "off"); rng("tt", "auto_tailor_top", String); rng("fu", "follow_up_days", String);
  rng("aps", "min_score", pct, ap); rng("apc", "daily_cap", String, ap);
  $("#sh", c).onchange = e => { f.sweep_hours = +e.target.value; mark(); };
  $("#dh", c).onchange = e => { f.digest_hour = +e.target.value; mark(); };
  $("#dgnow", c).onclick = async () => {
    try { const r = await api("/digest/send", { method: "POST" });
      const m = modal(r.sent ? "Summary sent" : "Today's summary", `<p class="small muted" style="margin-top:0">${r.sent ? `Sent to ${esc(r.to)}.` : esc(r.reason || "")}</p><b>${esc(r.subject)}</b><pre class="digest">${esc(r.preview)}</pre>`); }
    catch (e) { toast(e.message); }
  };
  $("#export", c).onclick = () => download("/export", "offerpilot-export.json").then(() => toast("Your data was downloaded")).catch(e => toast(e.message));
  $("#apon", c).onclick = e => { ap.enabled = !ap.enabled; e.currentTarget.setAttribute("aria-checked", String(ap.enabled)); mark(); };
  $("#discard", c).onclick = () => { S.dirty = false; S.animate = false; vSettings(c, part); };
  $("#save", c).onclick = async () => {
    try { const msg = await saveSettings(S.form); S.dirty = false; toast(msg, 6000); S.animate = false; vSettings(c, part); chrome(); }
    catch (e) { toast(e.message, 5000); }
  };
  $("#coadd", c).onclick = async () => {
    const url = $("#colink", c).value.trim(); if (!url) return;
    try { const r = await api("/companies/detect", { method: "POST", body: { url } });
      f.watch_companies = [...new Set([...(f.watch_companies || []), r.entry])]; mark(); toast(`Added ${r.entry} · ${r.open_jobs} open jobs — Save to keep it`, 6000); S.animate = false; vSettings(c, part); }
    catch (e) { toast(e.message, 7000); }
  };
  const gc = $("#gconnect", c);
  if (gc) gc.onclick = async () => { try { const { url } = await api("/gmail/connect"); location.href = url; } catch (e) { toast(e.message); } };
  const gd = $("#gdisc", c);
  if (gd) gd.onclick = async () => {
    if (!confirm("Disconnect Gmail? Sending and inbox reading stop until you connect again. Access is revoked at Google too.")) return;
    try { S.gmail = await api("/gmail/disconnect", { method: "POST" }); toast("Gmail disconnected"); S.animate = false; vSettings(c, part); } catch (e) { toast(e.message); }
  };
  const gs = $("#gsave", c);
  if (gs) gs.onclick = async () => {
    try { S.gmail = await api("/gmail/client", { method: "POST", body: { client_id: $("#gcid", c).value, client_secret: $("#gcs", c).value } }); toast("Saved — now connect your account"); S.animate = false; vSettings(c, part); }
    catch (e) { toast(e.message, 5000); }
  };
  $("#testsend", c).onclick = async () => {
    const to = prompt("Send a sample application to which address? (use your own)", ls.get("testto") || (S.profile || {}).email || "");
    if (!to) return; ls.set("testto", to);
    try { const r = await api("/test-send", { method: "POST", body: { to } }); toast(r.dry_run ? "Dry-run: nothing sent (start with DRY_RUN=0 to really send)" : "Sent — check your inbox"); }
    catch (e) { toast(e.message, 5000); }
  };
  mark();
}

// ---------------------------------------------------------------- profile (upload + editor)
function getPath(o, path) { return path.split(".").reduce((x, k) => x == null ? x : x[k], o); }
function setPath(o, path, v) { const ks = path.split("."), last = ks.pop(); ks.reduce((x, k) => x[k], o)[last] = v; }
async function vProfile(c) {
  if (!S.pdraft) { S.pdraft = structuredClone(S.profile); S.unver = null; S.parseInfo = null; S.pdirty = false; }
  const p = S.pdraft, u = S.unver || { skills: [], bullets: [], numbers: [] };
  const flagB = b => u.bullets.includes(b), flagS = s => u.skills.includes(s);
  const inp = (path, label, ph = "") => `<label class="field" style="margin:6px 0"><span class="small muted">${label}</span><input class="input" data-p="${path}" value="${esc(getPath(p, path) || "")}" placeholder="${esc(ph)}"></label>`;
  const lines = (path, label, rows = 4, flag = () => false) => { const arr = getPath(p, path) || [];
    return `<label class="field" style="margin:6px 0"><span class="small muted">${label}</span><textarea class="textarea ${arr.some(flag) ? "flagged" : ""}" style="min-height:${rows * 24}px" data-lines="${path}">${esc(arr.join("\n"))}</textarea></label>`; };
  const info = S.parseInfo;
  const issues = u.skills.length + u.bullets.length + u.numbers.length;
  c.innerHTML = `<div id="healthcard"></div><div id="proextras"></div><div class="view" style="display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));align-items:start">
    <div style="display:grid;gap:16px">
      <label class="drop" id="drop" tabindex="0">${I.upload}<b>Upload a new resume</b><span class="muted small">Drop a PDF, DOCX or TXT here, or click to choose. You'll review everything before it's saved.</span>
        <input type="file" id="file" accept=".pdf,.docx,.txt,.md" hidden></label>
      ${info ? `<div class="${issues ? "warnbox" : "okbox"}"><b>${issues ? `Check ${issues} item${issues > 1 ? "s" : ""} before saving` : "Everything extracted was found in your file"}</b><br>
        Read ${info.chars.toLocaleString()} characters with the ${esc(info.method === "rules" ? "rule-based parser" : info.method + " model")}.
        ${issues ? ` Highlighted fields contain text we couldn't find in your file${u.numbers.length ? ` (numbers: ${u.numbers.map(esc).join(", ")})` : ""} — fix or remove them; tailoring treats this profile as the truth.` : ""}
        ${info.llm_error ? `<br><span class="small">Model unavailable, used the rule-based parser.</span>` : ""}
        ${info.suggested_titles && info.suggested_titles.length ? `<div class="row" style="margin-top:8px;gap:6px"><span class="small">Suggested target titles:</span>${info.suggested_titles.map(x => `<span class="chip ai">${esc(x)}</span>`).join("")}<button class="btn sm" id="usetitles">Add to job targets</button></div>` : ""}</div>` : ""}
      <section class="card sec"><h3>Basics</h3>
        <div class="ed-grid">${inp("full_name", "Full name")}${inp("email", "Email")}${inp("phone", "Phone")}${inp("location", "Location", "City, Country")}</div>
        ${lines("links", "Links (one per line)", 2)}
        <label class="field"><span class="small muted">Summary</span><textarea class="textarea" style="min-height:110px" data-p="summary">${esc(p.summary)}</textarea></label>
        <div class="field"><div class="lab">Skills <span class="muted" style="font-weight:400">— the only skills tailoring may ever claim</span></div>
          <div class="tags" data-sk>${p.skills.map((s, i) => `<span class="chip ${flagS(s) ? "warn" : "ok"}" title="${flagS(s) ? "Not found in your file" : ""}">${esc(s)}<button data-rmsk="${i}" aria-label="Remove ${esc(s)}">×</button></span>`).join("")}<input placeholder="Add skill, press Enter" aria-label="Add skill"></div></div>
        ${lines("education", "Education (one per line)", 2)}${lines("certifications", "Certifications (one per line)", 2)}
      </section>
    </div>
    <div style="display:grid;gap:16px">
      <section class="card sec"><div class="row"><h3 class="grow">Experience</h3><button class="btn sm" id="addrole">+ Add role</button></div>
        ${p.experience.map((e, i) => `<div class="ed-role" style="animation-delay:${i * 40}ms"><div class="ed-grid">${inp(`experience.${i}.company`, "Company")}${inp(`experience.${i}.title`, "Title")}${inp(`experience.${i}.start`, "Start")}${inp(`experience.${i}.end`, "End")}</div>
          ${lines(`experience.${i}.bullets`, "Bullets (one per line)", Math.max(3, e.bullets.length + 1), flagB)}
          <button class="btn sm danger" data-rmrole="${i}">Remove role</button></div>`).join("")}
      </section>
      <section class="card sec"><div class="row"><h3 class="grow">Projects</h3><button class="btn sm" id="addproj">+ Add project</button></div>
        ${(p.projects || []).map((x, i) => `<div class="ed-role">${inp(`projects.${i}.name`, "Name")}
          <label class="field" style="margin:6px 0"><span class="small muted">Technologies (comma separated)</span><input class="input" data-csv="projects.${i}.technologies" value="${esc(x.technologies.join(", "))}"></label>
          ${lines(`projects.${i}.bullets`, "Bullets (one per line)", Math.max(2, x.bullets.length + 1))}<button class="btn sm danger" data-rmproj="${i}">Remove project</button></div>`).join("")}
      </section>
    </div>
  </div>
  <div class="savebar ${S.pdirty ? "on" : ""}" role="region" aria-label="Unsaved profile"><b>Profile changed</b><span class="small" style="opacity:.8">Saving re-scores every open job and re-tailors your best matches</span><span class="grow"></span>
    <button class="btn ghost" id="pdiscard" style="background:transparent;color:inherit">Discard</button><button class="btn" id="psave">Save & re-match jobs</button></div>`;
  const dirty = () => { S.pdirty = true; $(".savebar", c).classList.add("on"); };
  const redraw = () => { S.animate = false; const y = scrollY; vProfile(c).then(() => scrollTo(0, y)); };
  $$("[data-p]", c).forEach(el => el.oninput = () => { setPath(p, el.dataset.p, el.value); dirty(); });
  $$("[data-lines]", c).forEach(el => el.oninput = () => { setPath(p, el.dataset.lines, el.value.split("\n").map(s => s.trim()).filter(Boolean)); dirty(); });
  $$("[data-csv]", c).forEach(el => el.oninput = () => { setPath(p, el.dataset.csv, el.value.split(",").map(s => s.trim()).filter(Boolean)); dirty(); });
  const skIn = $("[data-sk] input", c);
  skIn.onkeydown = e => { if (e.key === "Enter" && skIn.value.trim()) { e.preventDefault(); if (!p.skills.includes(skIn.value.trim())) p.skills.push(skIn.value.trim()); dirty(); redraw(); } };
  $$("[data-rmsk]", c).forEach(b => b.onclick = () => { p.skills.splice(+b.dataset.rmsk, 1); dirty(); redraw(); });
  $$("[data-rmrole]", c).forEach(b => b.onclick = () => { p.experience.splice(+b.dataset.rmrole, 1); dirty(); redraw(); });
  $$("[data-rmproj]", c).forEach(b => b.onclick = () => { p.projects.splice(+b.dataset.rmproj, 1); dirty(); redraw(); });
  $("#addrole", c).onclick = () => { p.experience.unshift({ company: "", title: "", start: "", end: "Present", bullets: [], skills: [] }); dirty(); redraw(); };
  $("#addproj", c).onclick = () => { (p.projects = p.projects || []).unshift({ name: "", technologies: [], bullets: [] }); dirty(); redraw(); };
  const ut = $("#usetitles", c);
  if (ut) ut.onclick = async () => {
    const s = structuredClone(S.settings);
    s.target_titles = [...new Set([...s.target_titles, ...info.suggested_titles.map(x => x.toLowerCase())])];
    try { toast((await saveSettings(s)).replace("Saved", "Added to your job targets"), 6000); } catch (e) { toast(e.message); }
  };
  $("#pdiscard", c).onclick = () => { S.pdraft = null; redraw(); };
  $("#psave", c).onclick = async e => {
    const b = e.currentTarget; b.disabled = true; b.textContent = "Saving…";
    const body = { ...p, experience: p.experience.filter(x => x.company && x.title && x.bullets.length), projects: (p.projects || []).filter(x => x.name && x.bullets.length) };
    try {
      const out = await api("/profile", { method: "PUT", body });
      S.profile = out.profile; S.pdraft = null; S.unver = null; S.parseInfo = null; S.pdirty = false;
      const r = out.rescored; celebrate("Profile saved");
      if (out.retargeted) { S.settings = null; toast(`Your job search now looks for ${out.retargeted.to.slice(0, 4).join(", ")}${out.searching ? " — finding new jobs now" : ""}. Change it any time in Settings › Job preferences.`, 9000); if (out.searching) watchSweep(); }
      else toast(`Re-matched ${(r.scored || 0) + (r.skipped || 0)} jobs · ${out.tailoring} best matches re-tailoring`, 5000);
      redraw();
    } catch (x) { toast(x.message, 5000); b.disabled = false; b.textContent = "Save & re-match jobs"; }
  };
  profileExtras($("#proextras", c));
  if (!S.pdirty) healthCard($("#healthcard", c), t => {
    if (t.addSkill) { if (!p.skills.includes(t.addSkill)) p.skills.push(t.addSkill); dirty(); redraw(); return toast(`${t.addSkill} added — Save to keep it`); }
    const ta = $(`[data-lines="experience.${t.role}.bullets"]`, c);
    if (!ta) return;
    if (t.replace) {
      const arr = getPath(p, `experience.${t.role}.bullets`); arr[t.bullet] = t.replace; dirty(); redraw();
      return toast("Bullet updated — review it, then Save");
    }
    ta.scrollIntoView({ block: "center", behavior: "smooth" });
    const at = ta.value.indexOf(t.text); ta.focus(); if (at >= 0) ta.setSelectionRange(at, at + t.text.length);
  });
  const drop = $("#drop", c), file = $("#file", c);
  const handle = async f => {
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) return toast("That file is over 5 MB");
    drop.classList.add("busy"); $("b", drop).textContent = `Reading ${f.name}…`;
    const b64 = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1]); r.onerror = rej; r.readAsDataURL(f); });
    try {
      const out = await api("/profile/parse", { method: "POST", body: { filename: f.name, data_b64: b64 } });
      S.pdraft = { ...out.profile, preferences: S.profile.preferences }; S.unver = out.unverified; S.parseInfo = out; S.pdirty = true;
      toast("Resume read — review it, then Save"); redraw();
    } catch (x) { toast(x.message, 6000); drop.classList.remove("busy"); $("b", drop).textContent = "Upload a new resume"; }
  };
  drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } };
  file.onchange = () => handle(file.files[0]);
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => handle(e.dataTransfer.files[0]));
}

// ---------------------------------------------------------------- activity
async function vActivity(c) {
  const log = await api("/audit");
  const tone = a => a === "user" || a.startsWith("user") ? "warn" : a === "dispatch" ? "ok" : a === "tailor" || a === "orchestrator" ? "ai" : "info";
  c.innerHTML = `<div class="view card sec"><h3>Audit trail</h3><p>Append-only record of what every agent and you did.</p><div class="list">${log.slice(0, 150).map((e, i) =>
    `<div class="row" style="padding:7px 0;border-bottom:1px dashed var(--line);animation:rise .3s both;animation-delay:${Math.min(i, 30) * 15}ms">
      <span class="muted small" style="width:74px;font-variant-numeric:tabular-nums">${esc(new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))}</span>
      <span class="chip ${tone(e.actor)}">${esc(e.actor)}</span><b style="font-weight:600">${esc(e.event.replace(/_/g, " "))}</b>
      <span class="muted small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60ch">${esc(Object.entries(e.detail || {}).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "))}</span></div>`).join("")}</div></div>`;
}

// ---------------------------------------------------------------- review drawer
function wdiff(a, b) {   // word-level LCS diff -> html with <ins>/<del>; whitespace stays with its neighbours
  const A = a.split(/(\s+)/), B = b.split(/(\s+)/), n = A.length, m = B.length;
  if (n * m > 60000) return esc(b);
  const L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  const push = (k, s) => { const last = out[out.length - 1]; if (last && last[0] === k) last[1] += s; else out.push([k, s]); };
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { push("=", A[i]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) push("-", A[i++]);
    else push("+", B[j++]);
  }
  while (i < n) push("-", A[i++]);
  while (j < m) push("+", B[j++]);
  return out.map(([k, s]) => k === "=" ? esc(s) : k === "+" ? `<ins class="d">${esc(s)}</ins>` : `<del class="d">${esc(s)}</del> `).join("");
}
function similarity(a, b) {   // share of the original's words that survive IN ORDER (LCS) - reordering makes diffs unreadable
  const A = a.toLowerCase().split(/\W+/).filter(Boolean), B = b.toLowerCase().split(/\W+/).filter(Boolean);
  if (!A.length) return 1;
  if (A.length * B.length > 60000) return 0;
  let prev = new Uint16Array(B.length + 1);
  for (let i = 1; i <= A.length; i++) {
    const cur = new Uint16Array(B.length + 1);
    for (let j = 1; j <= B.length; j++) cur[j] = A[i - 1] === B[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], cur[j - 1]);
    prev = cur;
  }
  return prev[B.length] / Math.max(A.length, B.length);
}
function summaryHtml(orig, now, showDiff) {
  if (!showDiff || orig === now) return esc(now);
  if (similarity(orig, now) >= 0.6) return wdiff(orig, now);
  return `<ins class="d" style="background:none">${esc(now)}</ins><details class="small muted" style="margin-top:6px"><summary>Rewritten — show your original summary</summary>${esc(orig)}</details>`;
}
function highlight(text, good, bad) {
  const terms = [...good.map(t => [t, "k"]), ...bad.map(t => [t, "m"])].filter(([t]) => t && t.length > 1).sort((a, b) => b[0].length - a[0].length);
  if (!terms.length) return esc(text);
  const rx = new RegExp(`\\b(${terms.map(([t]) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\b`, "gi");
  const kind = Object.fromEntries(terms.map(([t, k]) => [t.toLowerCase(), k]));
  let out = "", last = 0;
  for (const m of text.matchAll(rx)) { out += esc(text.slice(last, m.index)) + `<mark class="${kind[m[0].toLowerCase()] || "k"}">${esc(m[0])}</mark>`; last = m.index + m[0].length; }
  return out + esc(text.slice(last));
}
function resumeHtml(p, a, showDiff) {
  const by = {}; for (const b of a.bullets) (by[b.source_company] = by[b.source_company] || []).push(b);
  const counts = {}; p.experience.forEach(e => counts[e.company] = (counts[e.company] || 0) + 1);
  const key = e => counts[e.company] > 1 ? `${e.company} (${e.title})` : e.company;
  return `<div class="resume"><h1>${esc(p.full_name)}</h1><div class="muted small">${esc([p.location, p.phone, p.email, ...(p.links || [])].filter(Boolean).join(" · "))}</div>
    <h5>Summary</h5><div>${summaryHtml(p.summary, a.tailored_summary, showDiff)}</div>
    <h5>Skills</h5><div class="row" style="gap:5px">${a.ordered_skills.map((s, i) => `<span class="chip ${i < 6 ? "ok" : ""}">${esc(s)}</span>`).join("")}</div>
    <h5>Experience</h5>${p.experience.map(e => `<h6>${esc(e.title)} <span class="muted" style="font-weight:400">— ${esc(e.company)} · ${esc(e.start)}–${esc(e.end)}</span></h6>
      <ul>${(by[key(e)] || []).map(b => `<li>${showDiff ? (similarity(b.original, b.rewritten) >= 0.6 ? wdiff(b.original, b.rewritten) : summaryHtml(b.original, b.rewritten, true)) : esc(b.rewritten)}</li>`).join("")}</ul>`).join("")}
    ${(p.projects || []).length ? `<h5>Projects</h5>${p.projects.map(x => `<h6>${esc(x.name)}</h6><ul>${x.bullets.map(b => `<li>${esc(b)}</li>`).join("")}</ul>`).join("")}` : ""}
    <h5>Education</h5>${p.education.map(e => `<div>${esc(e)}</div>`).join("")}</div>`;
}

async function openDrawer(id) {
  if (!S.drawer) S.opener = document.activeElement;
  S.drawer = id; history.replaceState(null, "", "#" + S.view + "/" + id);
  let scrim = $(".scrim:not(.closing)"), d = $(".drawer:not(.closing)");     // never reuse a panel that is fading out
  if (!d) {
    scrim = Object.assign(document.createElement("div"), { className: "scrim" });
    d = Object.assign(document.createElement("aside"), { className: "drawer" }); d.setAttribute("role", "dialog"); d.setAttribute("aria-modal", "true");
    document.body.append(scrim, d); scrim.onclick = closeDrawer;
    requestAnimationFrame(() => { scrim.classList.add("on"); d.classList.add("on"); });
  }
  d.innerHTML = `<div class="dh"><div class="sk" style="width:52px;height:52px;border-radius:50%"></div><div class="grow"><div class="sk" style="height:18px;width:40%"></div><div class="sk" style="height:12px;width:25%;margin-top:8px"></div></div></div>
    <div class="db"><div class="pane"><div class="sk" style="height:300px"></div></div><div class="pane"><div class="sk" style="height:400px"></div></div></div>`;
  let r;
  try { r = await api("/runs/" + id); if (S.drawer !== id) return; } catch (e) { toast(e.message); return closeDrawer(); }
  drawDrawer(d, r);
}
function closeDrawer() {
  S.drawer = null; history.replaceState(null, "", "#" + S.view);
  const s = $(".scrim:not(.closing)"), d = $(".drawer:not(.closing)"); if (!d) return;
  s && s.classList.add("closing"); d.classList.add("closing");
  s && s.classList.remove("on"); d.classList.remove("on"); setTimeout(() => { s && s.remove(); d.remove(); }, 450);
  render().then(() => { const o = S.opener; if (o && document.contains(o)) o.focus(); else $("#content").focus({ preventScroll: true }); });
}
document.addEventListener("keydown", e => { if (e.key === "Escape" && S.drawer && !$(".pop") && !$(".tk-modal") && !$(".cmdk-scrim")) closeDrawer(); });

function drawDrawer(d, r, tab = "resume") {
  const j = r.job || {}, a = r.adaptation, p = S.profile, st = r.status;
  const where = `${j.company} ${j.location}`.toLowerCase();
  const kw = r.keywords && r.keywords.total ? r.keywords : null;            // real skills and technical terms only
  const good = kw ? kw.have.map(x => x.key) : a ? a.matched_requirements : [], bad = (kw ? kw.missing.map(x => x.key) : a ? a.missing_requirements : []).filter(x => !where.includes(x.toLowerCase()));
  const s = r.match_score || 0;
  d.innerHTML = `
    <div class="dh" style="--h:${hue(j.company)}">
      <span class="dhlogo">${avatar(j.company, r.domain)}</span>
      <div class="ring" style="--p:0;--rc:${band(s) === "s3" ? "var(--emerald)" : band(s) === "s2" ? "var(--amber)" : "var(--mute)"}">${pct(r.match_score)}</div>
      <div class="grow" style="min-width:0"><h2>${esc(j.title)}</h2><div class="sub">${esc(j.company)} · ${esc(j.location || "—")} · ${src(j)} · <span class="chip ${st === "awaiting_approval" ? "warn" : ""}">${esc(STATUS[st] || st)}</span></div></div>
      <button class="icon-btn starbtn ${r.starred ? "on" : ""}" id="dstar" aria-pressed="${!!r.starred}" aria-label="${r.starred ? "Unstar" : "Star"} this job" title="Star">★</button>
      ${j.url ? `<a class="btn ghost" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">${I.ext}Posting</a>` : ""}
      <button class="icon-btn" id="dclose" aria-label="Close">${I.x}</button>
    </div>
    ${stepperHtml(st)}
    <div class="db">
      <div class="pane">${j.enriched_from ? `<div class="okbox" style="margin-top:0">${I.shield.replace("<svg", '<svg width="14" height="14" style="vertical-align:-2px"')} Full description from the company's own careers site (${esc(j.enriched_from)}).
          ${j.apply_url ? `<a href="${esc(j.apply_url)}" target="_blank" rel="noopener noreferrer">Company application page ↗</a>` : ""}</div>`
        : (j.description || "").length < 600 ? `<div class="warnbox" style="margin-top:0"><b>Only a short snippet from ${esc(src(j))}.</b>
            <div class="row" style="margin-top:8px"><button class="btn sm" id="findjd">${I.search}Search company careers sites</button><span class="small">or paste the job's link from the company site:</span></div>
            <div class="row" style="margin-top:6px;flex-wrap:nowrap"><label class="sr" for="jdlink">Job link</label><input class="input" id="jdlink" placeholder="https://careers.company.com/jobs/…" style="flex:1"><button class="btn sm" id="jdlinkgo">Get description</button></div></div>` : ""}
        ${verdictCard(r.verdict, r.breakdown)}
        <h4>Job description <span style="text-transform:none;letter-spacing:0;font-weight:400"> — <mark class="k">you have this</mark> <mark class="m">not in your profile</mark></span></h4>
        <div class="jd">${highlight(j.description || "No description in the source.", good, bad)}</div></div>
      <div class="pane">
        ${true ? `<div class="tabs" role="tablist">${[...(a ? [["resume", "Resume"], ["letter", "Letter"]] : []), ["match", "Match"], ["prep", "Prep"], ["company", "Company"], ["notes", "Notes"]]
            .map(([k, l]) => `<button role="tab" data-tab="${k}" aria-selected="${(a ? tab : "prep") === k}">${l}</button>`).join("")}<span class="ink"></span></div>
          <div id="tabp"></div>`
        : `<div class="empty big">${EMPTY.cards}<b>${st === "scored" || st === "skipped" ? "Not prepared yet" : ["discovered", "tailored"].includes(st) ? "Writing your application…" : "No documents"}</b>
            <span>${st === "scored" || st === "skipped" ? "Click “Prepare application” below. The AI writes a resume and cover letter for this job, using only facts from your profile." : esc(r.last_error || "")}</span></div>`}
      </div>
    </div>
    ${r.checks && r.checks.length ? checklistHtml(r.checks) : ""}
    <div class="df" style="position:relative">${actions(r)}</div>`;
  requestAnimationFrame(() => { const ring = $(".ring", d); ring && ring.style.setProperty("--p", Math.round(s * 100)); });
  d.setAttribute("aria-labelledby", "dtitle"); $("h2", d).id = "dtitle";
  if (!d.contains(document.activeElement)) $("#dclose", d).focus();
  d.onkeydown = e => {                      // keep keyboard focus inside the open panel
    if (e.key !== "Tab") return;
    const f = $$('a[href],button:not([disabled]),textarea,input,select,[tabindex="0"]', d).filter(x => x.offsetParent);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  };
  $("#dclose", d).onclick = closeDrawer;
  const showTab = k => {
    $$("[data-tab]", d).forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === k)));
    const on = $(`[data-tab="${k}"]`, d), ink = $(".ink", d);
    if (on && ink) { ink.style.left = on.offsetLeft + "px"; ink.style.width = on.offsetWidth + "px"; }
    const tp = $("#tabp", d); if (!tp) return;
    if (k === "prep") { prepTab(tp, r); return; }
    if (k === "notes") {
      tp.innerHTML = `<div class="tabpanel"><p class="small muted" style="margin-top:0">Private notes — people you spoke to, questions to ask, how you feel about the role. Saved automatically.</p>
        <textarea class="textarea" id="notes" style="min-height:260px" aria-label="Notes" placeholder="e.g. Recruiter: Priya · wants someone who has run incident response on AWS · ask about on-call">${esc(r.note || "")}</textarea>
        <div class="small muted" id="notesst" style="margin-top:6px"></div></div>`;
      const ta = $("#notes", tp); let timer = null;
      ta.oninput = () => { clearTimeout(timer); $("#notesst", tp).textContent = "Saving…";
        timer = setTimeout(async () => { try { await api(`/runs/${r.id}/note`, { method: "PUT", body: { note: ta.value } }); r.note = ta.value; $("#notesst", tp).textContent = "Saved"; } catch (e) { $("#notesst", tp).textContent = e.message; } }, 600); };
      return;
    }
    if (k === "company") {
      tp.innerHTML = '<div class="sk" style="height:220px"></div><p class="small muted">Researching public sources…</p>';
      api(`/intel?company=${encodeURIComponent(j.company)}`).then(dd => { if ($("#tabp", d) === tp) tp.innerHTML = `<div class="tabpanel">${intelHtml(dd)}</div>`; })
        .catch(e => tp.innerHTML = `<p class="muted">${esc(e.message)}</p>`);
      return;
    }
    if (k === "resume") {
      const diff = ls.get("diff") !== "0";
      tp.innerHTML = `<div class="tabpanel"><div class="row" style="margin-bottom:10px"><button class="switch violet" role="switch" id="diffsw" aria-checked="${diff}"><span class="track"></span><span>Highlight changes vs. your master resume</span></button>
        <span class="grow"></span><button class="btn sm" data-dl="resume">${I.ext}Download PDF</button></div>${resumeHtml(p, a, diff)}</div>`;
      $("#diffsw", tp).onclick = () => { ls.set("diff", diff ? "0" : "1"); showTab("resume"); };
    } else if (k === "letter") {
      const editable = ["awaiting_approval", "needs_manual"].includes(st);
      tp.innerHTML = `<div class="tabpanel">
        <div class="fieldrow"><span class="muted">To</span><span>${j.apply_email ? esc(j.apply_email) : '<span class="chip warn">No email — apply via the pre-filled form</span>'}</span></div>
        <div class="fieldrow"><span class="muted">Subject</span><span>Application: ${esc(j.title)} - ${esc(p.full_name)}</span></div>
        <div class="fieldrow"><span class="muted">Attached</span><span class="chip">${esc((r.resume_path || "resume").split("/").pop())}</span></div>
        <textarea class="textarea" id="cover" ${editable ? "" : "readonly"} aria-label="Cover letter">${esc(a.cover_letter)}</textarea>
        <div class="row" style="margin-top:8px"><span class="muted small" id="wc"></span><span class="grow"></span><button class="btn sm ghost" id="copycl">Copy</button>
          <button class="btn sm" data-dl="cover-letter">${I.ext}Download PDF</button>${editable ? '<button class="btn sm" id="savecl">Save edits</button>' : ""}</div></div>`;
      $("#copycl", tp).onclick = () => copyText($("#cover", tp).value);
      const ta = $("#cover", tp), wc = () => $("#wc", tp).textContent = `${ta.value.trim().split(/\s+/).filter(Boolean).length} words`;
      ta.oninput = wc; wc();
      const sv = $("#savecl", tp); if (sv) sv.onclick = async () => { try { await api(`/runs/${r.id}/cover`, { method: "PUT", body: { cover_letter: ta.value } }); a.cover_letter = ta.value; toast("Cover letter saved"); } catch (e) { toast(e.message); } };
    } else {
      requestAnimationFrame(() => { bindKeywordReport(tp, () => openDrawer(r.id)); const vp = $("#verpick", tp); if (vp) versionPicker(vp, r); });
      tp.innerHTML = `<div class="tabpanel">${keywordReport(r.keywords)}<div id="verpick"></div><div class="field"><div class="lab">You match (${good.length})</div><div class="row" style="gap:6px">${good.map(x => `<span class="chip ok">✓ ${esc(x)}</span>`).join("") || '<span class="muted">—</span>'}</div></div>
        <div class="field"><div class="lab">Not in your profile (${bad.length})</div><div class="row" style="gap:6px">${bad.map(x => `<span class="chip miss">✗ ${esc(x)}</span>`).join("") || '<span class="muted">—</span>'}</div>
          <div class="hint">These are reported, never claimed. The fact checker blocks any resume or letter that mentions them as your experience.</div></div>
        <div class="field"><div class="lab">History</div>${(r.audit || []).slice(0, 20).map(e => `<div class="row small" style="padding:3px 0"><span class="muted" style="width:52px">${esc(new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))}</span><span class="chip">${esc(e.actor)}</span>${esc(e.event.replace(/_/g, " "))}</div>`).join("")}</div></div>`;
    }
  };
  $$("[data-tab]", d).forEach(b => b.onclick = () => showTab(b.dataset.tab));
  d.onclick = ev => {                                      // downloads (resume / cover letter PDFs); assigned, so redraws never stack handlers
    const b = ev.target.closest("[data-dl]"); if (!b || !d.contains(b)) return;
    if (b.dataset.dl === "cover-letter" && $("#cover", d) && $("#cover", d).value !== (a && a.cover_letter) && !confirm("Download the last saved version? Your unsaved edits aren't included — click “Save edits” first to include them.")) return;
    b.disabled = true;
    download(`/runs/${r.id}/files/${b.dataset.dl}`, `${b.dataset.dl}.pdf`).then(() => toast("Downloaded")).catch(e => toast(e.message)).finally(() => b.disabled = false);
  };
  $("#dstar", d).onclick = async () => {
    const btn = $("#dstar", d), on = !r.starred;              // e.currentTarget is null after an await
    try { await api(`/runs/${r.id}/note`, { method: "PUT", body: { starred: on } }); r.starred = on;
      btn.classList.toggle("on", on); btn.setAttribute("aria-pressed", String(on)); btn.setAttribute("aria-label", `${on ? "Unstar" : "Star"} this job`);
      toast(on ? "Starred" : "Unstarred"); } catch (x) { toast(x.message); }
  };
  if ($("[data-tab]", d)) requestAnimationFrame(() => showTab(a ? tab : (["scored", "skipped", "filtered"].includes(st) ? "company" : "prep")));
  const lg = $("#jdlinkgo", d);
  if (lg) lg.onclick = async () => {
    const url = $("#jdlink", d).value.trim(); if (!url) return $("#jdlink", d).focus();
    lg.disabled = true; lg.textContent = "Reading…";
    try { const out = await api(`/runs/${r.id}/jd-from-link`, { method: "POST", body: { url } });
      toast(`Full description added (${out.source}) · match ${pct(out.score_before)} → ${pct(out.score_after)}${out.warning ? " · " + out.warning : ""}`, 8000);
      drawDrawer(d, await api("/runs/" + r.id), tab); }
    catch (e) { toast(e.message, 8000); lg.disabled = false; lg.textContent = "Get description"; }
  };
  const fj = $("#findjd", d);
  if (fj) fj.onclick = async () => {
    fj.disabled = true; fj.innerHTML = `<span class="spin" style="animation:spin .9s linear infinite">${I.refresh}</span>Searching the company's careers site…`;
    try { const out = await api(`/runs/${r.id}/research`, { method: "POST" });
      toast(out.jd.found ? `Full description found (${out.jd.source}) · match ${pct(out.jd.score_before)} → ${pct(out.jd.score_after)}` : "Couldn't find this role on a public careers board", 6000);
      drawDrawer(d, await api("/runs/" + r.id), tab); }
    catch (e) { toast(e.message); fj.disabled = false; }
  };
  bindActions(d, r);
}

async function prepTab(tp, r) {
  const show = kit => {
    tp.innerHTML = `<div class="tabpanel"><div class="row" style="margin-bottom:10px"><span class="muted small grow">Likely questions for this role, with talking points taken only from your real resume.${kit.method ? ` · by ${esc(kit.method)}` : ""}</span>
      <button class="btn sm" id="prepgo">${I.sparkle}${kit.questions ? "Regenerate" : "Generate prep kit"}</button></div>
      ${kit.questions ? `${kit.focus_areas && kit.focus_areas.length ? `<div class="row" style="gap:6px;margin-bottom:10px"><span class="small muted">Focus:</span>${kit.focus_areas.map(f => `<span class="chip ai">${esc(f)}</span>`).join("")}</div>` : ""}
        ${kit.questions.map((q, i) => `<div class="q" style="--i:${i}"><div class="row" style="flex-wrap:nowrap;align-items:flex-start"><b class="grow">${i + 1}. ${esc(q.question)}</b><button class="btn sm" data-prac="${i}">Practice</button></div><div class="why">${esc(q.why)}</div>
          ${q.talking_points.length ? `<ul>${q.talking_points.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : '<span class="chip warn">No matching experience — prepare an honest answer</span>'}</div>`).join("")}
        <div class="field"><div class="lab">Questions to ask them</div>${kit.ask_them.map(x => `<div class="bul">• ${esc(x)}</div>`).join("")}</div>`
      : `<div class="empty big">${EMPTY.cards}<b>No prep kit yet</b><span>Generate likely interview questions for ${esc((r.job || {}).company || "this company")}, mapped to your own experience.</span></div>`}</div>`;
    $$("[data-prac]", tp).forEach(b => b.onclick = () => { const m = modal("Practice", '<div id="pp"></div>', { wide: true }); practicePanel($("#pp", m.body), kit.questions[+b.dataset.prac].question, r.id); });
    $("#prepgo", tp).onclick = async e => { const b = e.currentTarget; b.disabled = true; b.innerHTML = `<span class="spin" style="animation:spin .9s linear infinite">${I.refresh}</span>Thinking… (up to a minute)`;
      try { show(await api(`/runs/${r.id}/prep`, { method: "POST" })); } catch (x) { toast(x.message); b.disabled = false; } };
  };
  tp.innerHTML = '<div class="sk" style="height:200px"></div>';
  show((await api(`/runs/${r.id}/prep`).catch(() => null)) || {});
}

function checklistHtml(checks) {
  const warn = checks.filter(c => c.level === "warn").length, block = checks.filter(c => c.level === "block").length;
  const ico = { ok: "✓", warn: "!", block: "✕", info: "i" };
  return `<details class="checks ${block ? "block" : warn ? "warn" : "ok"}" ${block || warn ? "open" : ""}><summary><b>Before you send:</b> ${block ? `${block} thing${block > 1 ? "s" : ""} to fix` : warn ? `${warn} thing${warn > 1 ? "s" : ""} to check` : "all good"}</summary>
    <ul>${checks.map(c => `<li class="${c.level}"><span aria-hidden="true">${ico[c.level]}</span>${esc(c.text)}</li>`).join("")}</ul></details>`;
}

function actions(r) {
  const st = r.status, j = r.job || {};
  const posting = j.url ? `<a class="btn ghost" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">${I.ext}Open posting</a>` : "";
  if (st === "scored" || st === "skipped") return `${posting}<span class="grow"></span><button class="btn primary" data-act="tailor">${I.sparkle}Prepare application</button>`;
  if (st === "awaiting_approval") return `<button class="btn" data-act="regen">${I.sparkle}Regenerate with feedback</button><button class="btn danger" data-act="reject">Reject</button>
    <button class="btn" data-act="form">${I.form}Open form (pre-filled)</button><span class="grow"></span><span class="muted small">${j.apply_email ? "Sends by email with your PDF resume" : "No email — approval moves it to “apply via form”"}</span>
    <button class="btn success" data-act="approve" ${(r.checks || []).some(c => c.level === "block") ? 'disabled title="Fix the checklist item first"' : ""}>${I.send}${j.apply_email ? "Approve & send" : "Approve"}</button>`;
  if (st === "needs_manual") {
    const board = /glassdoor\.|linkedin\.|naukri\.|indeed\.|foundit\.|instahyre\./i.test(j.url || "");
    return `<div class="applysteps" role="group" aria-label="How to apply">
      <b>Not applied yet.</b> This job has no email address, so you apply on the ${board ? "job site" : "company's website"} yourself:
      <ol><li>${board ? "Open the posting (opens in your normal browser, where you're logged in)" : "Open the form — we fill in your name, email, phone, LinkedIn and resume"}</li>
      <li>Check everything and press <b>Submit</b> on that website</li><li>Come back here and confirm</li></ol></div>
      <button class="btn" data-dl="resume">${I.ext}Resume PDF</button><button class="btn" data-dl="cover-letter">${I.ext}Cover letter PDF</button>
      <button class="btn primary" data-act="form">${I.ext}${board ? "1 · Open job posting" : "1 · Open application form"}</button>
      <button class="btn danger" data-act="drop">Not interested</button><span class="grow"></span>
      <button class="btn" data-act="applied">${I.check}3 · I pressed Submit there</button>`;
  }
  if (["discovered", "tailored"].includes(st)) return `<span class="spin" style="animation:spin .9s linear infinite">${I.refresh}</span><span>Writing your resume and cover letter… this updates by itself in about a minute.</span>`;
  if (st === "failed") return `${posting}<span class="grow"></span><button class="btn primary" data-act="regen">${I.sparkle}Try again</button>`;
  const later = ["submitted", "interview", "offer", "closed"].includes(st)
    ? `${r.adaptation ? `<button class="btn" data-dl="resume">${I.ext}Resume PDF</button>` : ""}<button class="btn" data-act="iv">${I.cal}Schedule interview</button>${st !== "offer" ? `<button class="btn" data-act="offer">Got an offer?</button>` : ""}` : "";
  return `${posting}${later}<span class="grow"></span><span class="muted small">${r.channel === "external" ? "Imported from a confirmation email in your Gmail" : st === "offer" ? "Offer received 🎉" : "Sent " + esc(ago(r.updated_at))}</span>`;
}

function bindActions(d, r) {
  const act = k => $(`[data-act="${k}"]`, d);
  const wait = async (fromUpdated) => {                 // poll until the run changes, keep the drawer live
    for (let i = 0; i < 120 && S.drawer === r.id; i++) {
      await sleep(3000);
      const n = await api("/runs/" + r.id).catch(() => null);
      if (n && (n.updated_at !== fromUpdated) && !["discovered", "tailored"].includes(n.status)) { drawDrawer(d, n); toast(n.adaptation ? "✨ Tailored documents ready" : "Updated"); return; }
    }
  };
  if (act("tailor")) act("tailor").onclick = async e => {
    e.currentTarget.disabled = true;
    try { await api(`/runs/${r.id}/tailor`, { method: "POST" }); } catch (x) { if (!/scored/.test(x.message)) return toast(x.message); await api(`/runs/${r.id}/regenerate`, { method: "POST", body: {} }); }
    $(".df", d).innerHTML = actions({ ...r, status: "discovered" }); toast("Queued — about a minute"); wait(r.updated_at);
  };
  if (act("regen")) act("regen").onclick = () => {
    if ($(".pop", d)) return $(".pop", d).remove();
    const pop = document.createElement("div"); pop.className = "card pop";
    pop.innerHTML = `<b>What should change?</b><div class="hint" style="margin:4px 0 8px">e.g. “lead with detection engineering”, “shorter cover letter”. Facts still come only from your profile.</div>
      <textarea class="textarea" style="min-height:80px" id="note" maxlength="500"></textarea><div class="row" style="margin-top:8px"><span class="grow"></span><button class="btn ghost" id="pcancel">Cancel</button><button class="btn primary" id="psend">${I.sparkle}Regenerate</button></div>`;
    $(".df", d).append(pop); $("#note", pop).focus();
    $("#pcancel", pop).onclick = () => pop.remove();
    $("#psend", pop).onclick = async () => {
      const note = $("#note", pop).value.trim();
      try { await api(`/runs/${r.id}/regenerate`, { method: "POST", body: { note } }); pop.remove();
        $(".df", d).innerHTML = actions({ ...r, status: "discovered" }); toast("Regenerating…"); wait(r.updated_at); }
      catch (e) { toast(e.message); }
    };
  };
  if (act("reject")) act("reject").onclick = async () => { try { await api(`/runs/${r.id}/decision`, { method: "POST", body: { decision: "reject" } }); toast("Rejected"); closeDrawer(); } catch (e) { toast(e.message); } };
  if (act("approve")) act("approve").onclick = async e => {
    const b = e.currentTarget; b.disabled = true;
    const cover = $("#cover", d) ? $("#cover", d).value : undefined;
    try {
      const out = await api(`/runs/${r.id}/decision`, { method: "POST", body: { decision: "approve", cover_letter: cover } });
      if (out.status === "submitted") { celebrate(S.agents.dispatch.dry_run ? "Approved (dry-run — nothing sent)" : "Application sent!"); setTimeout(() => { if (S.drawer === r.id) closeDrawer(); }, 1400); }
      else if (out.status === "needs_manual") { toast("Approved — now open the pre-filled form and submit it"); drawDrawer(d, await api("/runs/" + r.id), "letter"); }
      else { toast("Status: " + out.status.replace(/_/g, " ") + (out.last_error ? " — " + out.last_error : ""), 6000); drawDrawer(d, await api("/runs/" + r.id)); }
    } catch (x) { toast(x.message, 5000); b.disabled = false; }
  };
  if (act("form")) act("form").onclick = () => openForm(r.id);
  if (act("iv")) act("iv").onclick = () => interviewForm({ run_id: r.id, company: (r.job || {}).company, role: (r.job || {}).title });
  if (act("offer")) act("offer").onclick = () => offerForm({ run_id: r.id, company: (r.job || {}).company, role: (r.job || {}).title });
  if (act("applied")) act("applied").onclick = () => {
    if ($(".pop", d)) return $(".pop", d).remove();
    const opened = (r.audit || []).some(e => e.event === "open_form");
    const pop = document.createElement("div"); pop.className = "card pop"; pop.setAttribute("role", "alertdialog"); pop.setAttribute("aria-labelledby", "cfh");
    pop.innerHTML = `<b id="cfh">Did you press Submit on the ${esc((r.job || {}).company || "company")} website?</b>
      <div class="hint" style="margin:6px 0 10px">JobAgent can't submit website applications for you — this only records that <i>you</i> did.
      ${opened ? "" : "<br><b style='color:var(--amber)'>You haven't opened the application yet.</b>"} A confirmation email from the company usually follows within minutes; we'll pick it up from your Gmail.</div>
      <div class="row"><span class="grow"></span><button class="btn ghost" id="cfno">No, not yet</button><button class="btn success" id="cfyes">Yes, I submitted it</button></div>`;
    $(".df", d).append(pop); $("#cfno", pop).focus();
    $("#cfno", pop).onclick = () => pop.remove();
    $("#cfyes", pop).onclick = async () => {
      try { await api(`/runs/${r.id}/manual`, { method: "POST", body: { outcome: "applied", confirmed: true } }); pop.remove(); celebrate("Recorded as applied"); setTimeout(() => { if (S.drawer === r.id) closeDrawer(); }, 1300); }
      catch (e) { toast(e.message); }
    };
  };
  for (const k of ["drop"]) if (act(k)) act(k).onclick = async () => {
    try { await api(`/runs/${r.id}/manual`, { method: "POST", body: { outcome: "dropped" } });
      if (k === "applied") { celebrate("Marked as applied"); setTimeout(() => { if (S.drawer === r.id) closeDrawer(); }, 1300); } else { toast("Dropped"); closeDrawer(); } }
    catch (e) { toast(e.message); }
  };
}
async function openForm(id) {
  try {
    const r = await api(`/runs/${id}/open-form`, { method: "POST" });
    toast(r.mode === "browser" ? `Opened on ${r.host.replace("www.", "")} in your browser — apply there, then come back and confirm`
                               : "A browser window is opening with your details filled in — check them and press Submit there", 7000);
    if (S.drawer === id) drawDrawer($(".drawer"), await api("/runs/" + id));      // refresh so step 3 knows the form was opened
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- celebration
function celebrate(msg) {
  const o = document.createElement("div"); o.className = "celebrate";
  o.innerHTML = `<div style="display:grid;justify-items:center"><div class="badge"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div><div class="msg">${esc(msg)}</div></div>`;
  document.body.append(o); setTimeout(() => o.remove(), 1600);
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || A11Y.get().motion) return;
  const cv = document.createElement("canvas"); cv.className = "confetti"; document.body.append(cv);
  const ctx = cv.getContext("2d"), W = cv.width = innerWidth, H = cv.height = innerHeight;
  const cols = document.documentElement.dataset.theme === "neo" ? ["#22d3ee", "#a855f7", "#818cf8", "#34d399", "#f0abfc", "#67e8f9"]
    : ["#059669", "#7c3aed", "#4f46e5", "#f59e0b", "#e11d48", "#0ea5e9"];
  const ps = Array.from({ length: 140 }, () => ({ x: W / 2, y: H / 2, vx: (Math.random() - .5) * 16, vy: Math.random() * -15 - 4, r: Math.random() * 6 + 3, c: cols[Math.random() * cols.length | 0], a: Math.random() * 6, va: (Math.random() - .5) * .3 }));
  let t = 0;
  (function f() {
    ctx.clearRect(0, 0, W, H);
    for (const p of ps) { p.vy += .45; p.vx *= .99; p.x += p.vx; p.y += p.vy; p.a += p.va;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillStyle = p.c; ctx.globalAlpha = Math.max(0, 1 - t / 110); ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2); ctx.restore(); }
    if (++t < 110) requestAnimationFrame(f); else cv.remove();
  })();
}

// ---------------------------------------------------------------- command palette (⌘K / Ctrl+K)
function palette() {
  if ($(".cmdk-scrim")) return;
  const cmds = [
    ...VIEWS.map(([k, l]) => ({ label: `Go to ${l}`, hint: "view", run: () => go(k) })),
    { label: "Refresh jobs from all sources", hint: "action", run: refreshJobs },
    { label: "Upload a new resume", hint: "action", run: () => { go("profile"); setTimeout(() => $("#file") && $("#file").click(), 400); } },
    { label: "Check Gmail inbox now", hint: "action", run: async () => { const r = await api("/inbox/poll", { method: "POST" }); toast(r.ok ? `${r.kept} job-related emails` : r.error); } },
    { label: "Change theme", hint: "action", run: () => $("#theme").click() },
    { label: "Schedule an interview", hint: "action", run: () => interviewForm() },
    { label: "Add an offer", hint: "action", run: () => offerForm() },
    { label: "Quick review: go through new matches one at a time", hint: "action", run: () => quickReview() },
    { label: "Ask the assistant how to do something", hint: "help", run: () => askToggle(true) },
    { label: "Email a recruiter (add outreach contact)", hint: "action", run: () => { go("outreach"); setTimeout(() => outreachForm(), 400); } },
    { label: "Practise interview questions", hint: "action", run: () => { S.ivTab = "practice"; go("interviews"); } },
    { label: "Add a job from another website", hint: "action", run: () => window.open("/clip", "_blank") },
    { label: "Check my resume health", hint: "action", run: () => { S.setTab = "profile"; go("settings"); } },
    ...[...new Set(S.runs.map(r => r.job && r.job.company).filter(Boolean))].map(co => ({ label: `Research ${co}`, hint: "company", run: () => companyPanel(co) })),
  ];
  const jobs = S.runs.filter(r => r.job).map(r => ({ label: `${r.job.title} — ${r.job.company}`, hint: `${pct(r.match_score)} · ${r.status.replace(/_/g, " ")}`, run: () => openDrawer(r.id) }));
  const scrim = document.createElement("div"); scrim.className = "cmdk-scrim";
  scrim.innerHTML = `<div class="cmdk" role="dialog" aria-label="Command palette"><input placeholder="Search jobs, views and actions…" aria-label="Search"><ul role="listbox"></ul></div>`;
  document.body.append(scrim);
  const inp = $("input", scrim), ul = $("ul", scrim);
  let sel = 0, list = [];
  const draw = () => {
    const q = inp.value.toLowerCase().trim();
    list = (q ? [...cmds, ...jobs].filter(x => x.label.toLowerCase().includes(q)) : cmds).slice(0, 40);
    sel = Math.min(sel, Math.max(0, list.length - 1));
    ul.innerHTML = list.map((x, i) => `<li role="option" aria-selected="${i === sel}" data-i="${i}">${esc(x.label)}<small>${esc(x.hint)}</small></li>`).join("") || '<li class="muted">No matches</li>';
    $$("[data-i]", ul).forEach(li => li.onclick = () => pick(+li.dataset.i));
    const on = $('[aria-selected="true"]', ul); on && on.scrollIntoView({ block: "nearest" });
  };
  const close = () => scrim.remove();
  const pick = i => { const x = list[i]; close(); x && x.run(); };
  inp.oninput = () => { sel = 0; draw(); };
  inp.onkeydown = e => {
    if (e.key === "ArrowDown") { sel = Math.min(list.length - 1, sel + 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); }
    else if (e.key === "Enter") pick(sel);
    else if (e.key === "Escape") close();
  };
  scrim.onclick = e => { if (e.target === scrim) close(); };
  draw(); inp.focus();
}
document.addEventListener("keydown", e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette(); } });

// ---------------------------------------------------------------- help centre
const STATUS_HELP = [["New", "Matched to your profile. Prepare an application when you like it."], ["Preparing…", "The AI is writing the resume and cover letter."],
  ["Ready for you", "Written and fact-checked. Read, edit if you want, then approve."], ["Not applied yet — apply on website", "No email address: apply on the company's site, then confirm."],
  ["Applied", "Sent by email, or you confirmed you submitted it on the website."], ["Interview", "A recruiter asked to talk."],
  ["Hidden by filters", "Doesn't meet your current preferences; comes back if you loosen them."], ["Low match", "Below your minimum match score."]];
async function vHelp(c) {
  const B = window.BRAND || {};
  c.innerHTML = `<div class="view helpgrid">
    <section class="card sec wide"><h3>How ${esc(B.name || "it")} works</h3><ol class="howto">
      <li><b>Your profile is the source of truth.</b> Everything written for you comes from your resume. A fact-checker blocks anything it can't trace back to it.</li>
      <li><b>Find jobs.</b> Remote boards, company career sites and your job-alert emails. Each job gets a match score.</li>
      <li><b>Prepare.</b> The best matches get a tailored resume and cover letter automatically; prepare any other job with one click.</li>
      <li><b>You approve.</b> Nothing is sent until you click. Email applications send from your Gmail; website applications open for you to submit.</li>
      <li><b>Follow through.</b> Replies are sorted in your Inbox with drafts ready, and each job has an interview-prep kit.</li></ol>
      <div class="row" style="margin-top:12px"><button class="btn primary" id="rerun">Run the setup guide</button><a class="btn" href="/welcome" target="_blank" rel="noopener">Product overview ↗</a></div></section>
    <section class="card sec"><h3>What the statuses mean</h3><dl class="kv">${STATUS_HELP.map(([s, d]) => `<dt><span class="chip">${esc(s)}</span></dt><dd>${esc(d)}</dd>`).join("")}</dl></section>
    <section class="card sec"><h3>Safety & privacy</h3><ul class="plain">
      <li>Practice mode sends nothing; live mode sends only what you approve.</li><li>Gmail access is send + read-only; only job-related mail is read, and other mail is never stored.</li>
      <li>LinkedIn, Naukri, Glassdoor and Indeed are never automated — their jobs arrive via your alert emails.</li>
      <li>Company research uses public sources only and never profiles individual people.</li><li>Your data stays in the app's folder on this computer.</li></ul></section>
    <section class="card sec"><h3>Interviews, practice & offers</h3><ul class="plain">
      <li><b>Schedule</b> from an invite email (Inbox › “Add to interviews”) — times in the email are suggested for you — and add it to your calendar with one click.</li>
      <li><b>Practise</b> any prep-kit question: write or dictate an answer and get feedback on structure (STAR), evidence and length, with your real experience to cite.</li>
      <li><b>After the interview</b>, send a thank-you note from the Interviews page — drafted for you, sent from your Gmail.</li>
      <li><b>Offers</b>: compare packages side by side, check them against salaries in your job list, and draft a negotiation email that only uses numbers you entered.</li></ul></section>
    <section class="card sec"><h3>Deciding and tailoring</h3><ul class="plain">
      <li><b>Should I apply?</b> Every job opens with a verdict and its reasons, including the years of experience asked against yours.</li>
      <li><b>Keyword report</b> (a job's Match tab): the skills and terms the posting uses, which your resume has, and which are missing.</li>
      <li><b>Resume versions and designs</b> (Settings › Profile & resume): keep a resume per kind of role and choose from four ATS-safe layouts.</li>
      <li><b>Salary explorer</b> (Insights): pay by role and city from the listings you've seen.</li>
      <li><b>People and LinkedIn</b> (Outreach): track referrers and contacts, and review your LinkedIn profile text.</li>
      <li><b>Browser extension</b> (Settings › Gmail & sending): fills contact details on application forms; you press Submit.</li></ul></section>
    <section class="card sec"><h3>Ask the assistant</h3><p style="margin:0 0 10px;color:var(--ink-2)">The <b>Ask</b> button (bottom right) knows how every feature works and can take you straight to it. Try “What should I do next?” — it looks at your own search to answer.</p>
      <button class="btn primary" id="helpask">Open the assistant</button></section>
    <section class="card sec"><h3>Outreach: email recruiters directly</h3><ul class="plain">
      <li><b>Find the person yourself</b> — “Find HR or recruiters on LinkedIn” opens LinkedIn in your own browser. Add their name and any <i>public</i> email. We never scrape LinkedIn or guess addresses.</li>
      <li><b>A personal email and a tailored CV</b> are prepared from your real profile and the job posting. Add one sentence of your own about the company — it matters most.</li>
      <li><b>You approve every email.</b> “Send all approved” then sends them one at a time, about a minute apart, within your daily limit.</li>
      <li><b>Drafts write themselves:</b> after each refresh, Outreach prepares a draft for each of your best new matches (you choose how many in Settings). You add who to write to, read it, and approve.</li>
      <li><b>The tracker</b> shows drafts, sent, replied and interviews, finds replies in your Gmail, and reminds you of one follow-up after 5 days.</li>
      <li>Every email includes an opt-out line. Anyone who says no is never contacted again.</li></ul></section>
    <section class="card sec"><h3>Save jobs from anywhere</h3><p style="margin:0;color:var(--ink-2)">Add the “Save to ${esc((window.BRAND || {}).name || "OfferPilot")}” button to your bookmarks bar (Settings › Gmail & sending). On any job page — LinkedIn, Naukri, a company site — click it to save the job with its full description. Or use “Add a job” on the Jobs page.</p></section>
    <section class="card sec"><h3>Keyboard shortcuts</h3>${shortcutList()}</section>
    <section class="card sec"><h3>Common questions</h3>
      <details><summary>Why is a job “Low match”?</summary><p>Its requirements overlap little with your profile. Lower the minimum in Settings › Job preferences, or add skills you genuinely have to your profile.</p></details>
      <details><summary>Why didn't I get a confirmation email?</summary><p>Website applications are only submitted when you press Submit on the company's site. Email applications only send in live mode.</p></details>
      <details><summary>Can I change the writing style?</summary><p>Yes — Settings › Job preferences › Writing style, then “Regenerate” on any prepared application.</p></details>
      <details><summary>How do I get LinkedIn jobs?</summary><p>Turn on LinkedIn job alerts for your searches. They arrive in Gmail and appear here after the next search.</p></details></section>
  </div>`;
  $("#rerun", c).onclick = () => onboarding(true);
  $("#helpask", c).onclick = () => askToggle(true);
}

// ---------------------------------------------------------------- first-run setup guide
async function onboarding(force = false, startAt = null) {
  if ($(".wizard")) return;
  const steps = ["Your resume", "What you're looking for", "Connect Gmail", "Find your first jobs"];
  let i = startAt ?? +(ls.get("onboardStep") || 0);
  const w = document.createElement("div"); w.className = "cmdk-scrim wizard-scrim";
  w.innerHTML = `<div class="wizard" role="dialog" aria-modal="true" aria-labelledby="wzt"><div class="wz-head"><span class="blogo">${(window.BRAND || {}).logo || ""}</span>
      <div class="grow"><h2 id="wzt">Set up ${esc((window.BRAND || {}).name || "")}</h2><div class="wz-steps" aria-hidden="true"></div></div>
      <button class="btn ghost sm" id="wzskip">Skip for now</button></div><div class="wz-body" tabindex="-1"></div><div class="wz-foot"></div></div>`;
  document.body.append(w);
  const done = () => { ls.set("onboarded", "1"); ls.set("onboardStep", "0"); w.remove(); render(); };
  $("#wzskip", w).onclick = done;
  w.addEventListener("keydown", e => { if (e.key === "Escape") done(); });
  const draw = async () => {
    ls.set("onboardStep", String(i));
    $(".wz-steps", w).innerHTML = steps.map((s, k) => `<span class="${k < i ? "done" : k === i ? "on" : ""}">${k < i ? "✓" : k + 1} ${esc(s)}</span>`).join("");
    const body = $(".wz-body", w), foot = $(".wz-foot", w);
    const nav = (next = "Continue", canNext = true) => { foot.innerHTML = `${i ? '<button class="btn ghost" id="wzback">Back</button>' : ""}<span class="grow"></span><button class="btn primary" id="wznext" ${canNext ? "" : "disabled"}>${next}</button>`;
      if ($("#wzback", foot)) $("#wzback", foot).onclick = () => { i--; draw(); }; };
    if (i === 0) {
      const p = S.profile || {}, real = p.full_name && p.full_name !== "Alex Morgan";
      body.innerHTML = `<h3>Start with your resume</h3><p class="muted">Everything the app writes for you comes from it — nothing is ever invented.</p>
        ${real ? `<div class="okbox">✓ Using the resume for <b>${esc(p.full_name)}</b> — ${p.skills.length} skills, ${p.experience.length} roles. Upload a newer one below if it has changed.</div>` : ""}
        <label class="drop" id="wzdrop" tabindex="0">${I.upload}<b>Drop your resume here</b><span class="muted small">PDF, DOCX or TXT · or click to choose</span><input type="file" id="wzfile" accept=".pdf,.docx,.txt,.md" hidden></label><div id="wzres"></div>`;
      nav("Continue", real);
      const drop = $("#wzdrop", body), file = $("#wzfile", body);
      const handle = async f => { if (!f) return; drop.classList.add("busy"); $("b", drop).textContent = `Reading ${f.name}…`;
        const b64 = await new Promise(res => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1]); r.readAsDataURL(f); });
        try { const out = await api("/profile/parse", { method: "POST", body: { filename: f.name, data_b64: b64 } });
          const issues = out.unverified.skills.length + out.unverified.bullets.length;
          $("#wzres", body).innerHTML = `<div class="${issues ? "warnbox" : "okbox"}"><b>${esc(out.profile.full_name)}</b> — ${out.profile.skills.length} skills, ${out.profile.experience.length} roles, ${out.profile.projects.length} projects.
            ${issues ? `${issues} item(s) couldn't be matched to your file — review them later in Settings › Profile.` : "Everything was verified against your file."}</div>`;
          const saved = await api("/profile", { method: "PUT", body: { ...out.profile, preferences: S.profile.preferences } });
          S.profile = saved.profile; if (saved.retargeted) S.settings = null; if (out.suggested_titles && out.suggested_titles.length) S.suggest = out.suggested_titles;
          drop.classList.remove("busy"); $("b", drop).textContent = "Uploaded ✓"; nav("Continue", true); $("#wznext", foot).onclick = () => { i++; draw(); }; }
        catch (e) { toast(e.message, 6000); drop.classList.remove("busy"); $("b", drop).textContent = "Drop your resume here"; } };
      file.onchange = () => handle(file.files[0]); drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } };
      ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
      ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
      drop.addEventListener("drop", e => handle(e.dataTransfer.files[0]));
      if ($("#wznext", foot)) $("#wznext", foot).onclick = () => { i++; draw(); };
    } else if (i === 1) {
      const s = structuredClone(S.settings || await api("/settings"));
      const titles = [...new Set([...(s.target_titles || []), ...((S.suggest || []).map(x => x.toLowerCase()))])];
      body.innerHTML = `<h3>What are you looking for?</h3><p class="muted">You can fine-tune all of this later in Settings.</p>
        <label class="field"><span class="lab">Job titles (comma separated)</span><input class="input" id="wzt1" value="${esc(titles.join(", "))}" placeholder="e.g. security engineer, detection engineer"></label>
        <label class="field"><span class="lab">Where (comma separated)</span><input class="input" id="wzt2" value="${esc((s.target_locations || []).join(", "))}" placeholder="e.g. Bengaluru, India"></label>
        <div class="field"><span class="lab">Work style</span><div class="seg" role="group">${["remote", "hybrid", "onsite"].map(m => `<button aria-pressed="${s.work_modes.includes(m)}" data-wm="${m}">${m[0].toUpperCase() + m.slice(1)}</button>`).join("")}</div></div>
        <label class="field"><span class="lab">Minimum salary <span class="rangeval" id="wzsv">${s.min_salary_lpa ? "₹" + s.min_salary_lpa + " LPA" : "any"}</span></span><input type="range" id="wzs" min="0" max="60" value="${s.min_salary_lpa || 0}"></label>`;
      $$("[data-wm]", body).forEach(b => b.onclick = () => { const m = b.dataset.wm, on = s.work_modes.includes(m); if (on && s.work_modes.length === 1) return;
        s.work_modes = on ? s.work_modes.filter(x => x !== m) : [...s.work_modes, m]; b.setAttribute("aria-pressed", String(!on)); });
      $("#wzs", body).oninput = e => { s.min_salary_lpa = +e.target.value; $("#wzsv", body).textContent = s.min_salary_lpa ? `₹${s.min_salary_lpa} LPA` : "any"; };
      nav("Save and continue");
      $("#wznext", foot).onclick = async () => {
        s.target_titles = $("#wzt1", body).value.split(",").map(x => x.trim().toLowerCase()).filter(Boolean);
        s.target_locations = $("#wzt2", body).value.split(",").map(x => x.trim()).filter(Boolean);
        try { await saveSettings(s); i++; draw(); } catch (e) { toast(e.message, 6000); } };
    } else if (i === 2) {
      let gm = await api("/gmail/status").catch(() => ({}));
      body.innerHTML = `<h3>Connect your Gmail</h3><p class="muted">Used to send applications you approve, read recruiter replies, and pick up LinkedIn / Naukri / Glassdoor job alerts. Permissions: send + read-only.</p>
        ${gm.connected ? `<div class="okbox">✓ Connected as <b>${esc(gm.address || "your account")}</b></div>` : gm.has_client
          ? `<button class="btn primary" id="wzg">${I.mail}Connect Gmail</button><p class="small muted">You'll sign in with Google and come straight back here.</p>`
          : `<div class="warnbox">Gmail needs a one-time Google setup (an OAuth client). You can do it later in Settings › Gmail & sending.</div>`}`;
      nav(gm.connected ? "Continue" : "Skip this step");
      const g = $("#wzg", body); if (g) g.onclick = async () => { try { const { url } = await api("/gmail/connect"); ls.set("onboardStep", "2"); ls.set("onboardResume", "1"); location.href = url; } catch (e) { toast(e.message); } };
      $("#wznext", foot).onclick = () => { i++; draw(); };
    } else {
      body.innerHTML = `<h3>Find your first jobs</h3><p class="muted">Searches job boards, company career sites and your job-alert emails, then scores every job against your resume and prepares the best ones.</p>
        <button class="btn primary big" id="wzgo">${I.refresh}Search now</button><div id="wzout" class="small muted" style="margin-top:12px"></div>`;
      nav("Finish", true);
      $("#wzgo", body).onclick = async e => { e.currentTarget.disabled = true; $("#wzout", body).textContent = "Searching… this takes about a minute.";
        await refreshJobs(); $("#wzout", body).textContent = S.sweepNote; };
      $("#wznext", foot).onclick = () => { done(); go("jobs"); };
    }
    $(".wz-body", w).focus();
  };
  draw();
}

// ---------------------------------------------------------------- quiet background updates
function signature() {
  return JSON.stringify([S.runs.map(r => [r.id, r.status, r.match_score, r.updated_at, r.job && r.job.enriched_from]),
                         S.emails.map(m => [m.id, m.replied_at])]);
}
async function backgroundUpdate(force = false) {
  if (document.hidden && !force) return;
  if (!force) {                               // one tiny request; the full lists are fetched only when something changed
    try { const p = await api("/pulse"); if (S.pulse && p.sig === S.pulse) return; } catch { return; }
  }
  const before = signature();
  try { await load(); } catch { return; }
  chrome();                                   // badges, status dot, counts: always cheap and safe
  if (signature() === before && !force) return;          // nothing changed -> nothing redraws
  const busy = S.drawer || S.dirty || S.pdirty || $(".composer") || $(".statuspop") || $(".cmdk-scrim") ||
               document.activeElement?.matches("input,textarea,select") || Date.now() - (S.lastActive || 0) < 20000;
  if (busy && !force) { showUpdatesPill(); return; }
  hideUpdatesPill();
  const y = scrollY; S.animate = false;
  const c = $("#content"); c.classList.add("noanim");
  interviewReminders();
  const fn = { home: vHome, jobs: vJobs, applications: vApps, inbox: vInbox, companies: vCompanies, insights: vInsights, help: vHelp }[S.view];
  if (fn && !(S.view === "settings")) { await fn(c); scrollTo(0, y); }          // settings never auto-redraws
}
function showUpdatesPill() {
  if ($(".updpill")) return;
  const b = document.createElement("button"); b.className = "updpill"; b.innerHTML = `${I.refresh}New updates — show`;
  b.onclick = () => { S.lastActive = 0; backgroundUpdate(true); };
  document.body.append(b);
}
function hideUpdatesPill() { const p = $(".updpill"); if (p) p.remove(); }

// ---------------------------------------------------------------- boot
addEventListener("DOMContentLoaded", function boot() {
  setTheme(THEMES[ls.get("theme")] ? ls.get("theme") : "studio", true);
  A11Y.apply();
  shell();
  const [hash, query] = (location.hash.slice(1) || "home").split("?");
  const [v, run] = hash.split("/");
  const gq = new URLSearchParams(query || "").get("gmail");
  if (gq) { setTimeout(() => toast(gq === "connected" ? "✅ Gmail connected" : "Gmail: " + gq, 6000), 400); history.replaceState(null, "", "#" + v); }
  { const [vv, sub] = ALIAS[v] || [v]; if (vv === "jobs" && sub) S.jobsTab = sub; if (vv === "settings" && sub) S.setTab = sub; S.view = VIEWS.some(x => x[0] === vv) ? vv : "home"; }
  render().then(() => {
    if (run) openDrawer(run);
    const incomplete = !S.profile || S.profile.full_name === "Alex Morgan" || !S.runs.length;
    if (ls.get("onboardResume") === "1") { ls.set("onboardResume", "0"); onboarding(true, 2); }
    else if (!ls.get("onboarded") && incomplete) onboarding();
  });
  document.addEventListener("keydown", e => {
    if (e.metaKey || e.ctrlKey || e.altKey || document.activeElement?.matches("input,textarea,select,[contenteditable]") || $(".cmdk-scrim") || S.drawer) return;
    if (e.key === "?") { e.preventDefault(); shortcuts(); }
    else if (/^[1-9]$/.test(e.key)) go(VIEWS[+e.key - 1][0]);
    else if (e.key === "n") refreshJobs();
    else if (e.key === "/") { e.preventDefault(); if (S.view !== "jobs") { go("jobs"); setTimeout(() => $("#q") && $("#q").focus(), 350); } else $("#q") && $("#q").focus(); }
  });
  addEventListener("hashchange", () => {        // links, back/forward, typed URLs
    const [hraw, hr] = location.hash.slice(1).split("?")[0].split("/");
    const hv = (ALIAS[hraw] || [hraw])[0];
    if ((VIEWS.some(x => x[0] === hv) || ALIAS[hraw]) && (hv !== S.view || ALIAS[hraw])) { if (S.drawer && !hr) closeDrawer(); go(hraw, false); }
    if (hr && hr !== S.drawer) openDrawer(hr);
  });
  // Background updates: poll quietly, update badges/status, and only redraw the page when something really changed.
  // Never redraw under someone who is reading, scrolling, typing or has a panel open - offer a button instead.
  ["scroll", "keydown", "pointerdown", "wheel", "touchstart"].forEach(ev => addEventListener(ev, () => { S.lastActive = Date.now(); }, { passive: true, capture: true }));
  setInterval(backgroundUpdate, 30000);
});
