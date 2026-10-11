"use strict";
// Visual helpers: trend lines, activity grid, one-time count-up, skill-fit bars and empty-state illustrations.
// Loaded after app.js; depends on esc, S, EMPTY, I.

const reducedMotion = () => document.documentElement.dataset.motion === "reduce" || matchMedia("(prefers-reduced-motion: reduce)").matches;

// A small trend line. Decorative next to a number that is already stated, so it carries a text summary instead of axes.
function sparkline(values, label) {
  const v = values || [], n = v.length; if (n < 2) return "";
  const max = Math.max(1, ...v), w = 120, h = 30, x = i => (i / (n - 1)) * w, y = t => h - 3 - (t / max) * (h - 8);
  const pts = v.map((t, i) => `${x(i).toFixed(1)},${y(t).toFixed(1)}`).join(" ");
  const total = v.reduce((a, b) => a + b, 0);
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}: ${total} in the last ${n} days"><title>${esc(label)}: ${total} in the last ${n} days</title>
    <polygon points="0,${h} ${pts} ${w},${h}" class="sparkfill"/><polyline points="${pts}" class="sparkline" fill="none" vector-effect="non-scaling-stroke"/>
    <circle cx="${x(n - 1).toFixed(1)}" cy="${y(v[n - 1]).toFixed(1)}" r="2.6" class="sparkdot"/></svg>`;
}

// 12 weeks of activity, one square per day, Monday first. One hue, light to dark; every square has its date and count as a tooltip.
function activityGrid(days, counts, noun = "application") {
  if (!days || !days.length) return "";
  const cells = days.map((d, i) => ({ d: new Date(d + "T00:00"), n: counts[i] || 0 }));
  const lead = (cells[0].d.getDay() + 6) % 7, max = Math.max(1, ...cells.map(c => c.n));
  const level = n => n === 0 ? 0 : Math.min(4, Math.ceil((n / max) * 4));
  const fmt = d => d.toLocaleDateString([], { day: "numeric", month: "short" });
  const total = cells.reduce((a, c) => a + c.n, 0), active = cells.filter(c => c.n).length;
  return `<div class="agrid-wrap"><div class="agrid" role="img" aria-label="${total} ${noun}${total === 1 ? "" : "s"} on ${active} day${active === 1 ? "" : "s"} in the last ${Math.round(cells.length / 7)} weeks">
      ${"<i class='pad'></i>".repeat(lead)}${cells.map((c, i) => `<i class="l${level(c.n)}" style="--n:${i}" title="${esc(fmt(c.d))}: ${c.n} ${noun}${c.n === 1 ? "" : "s"}"></i>`).join("")}</div>
    <div class="agrid-key small muted"><span>${esc(fmt(cells[0].d))}</span><span class="grow"></span>Less <i class="l0"></i><i class="l1"></i><i class="l2"></i><i class="l3"></i><i class="l4"></i> More</div></div>`;
}

// A route with five waypoints, one for each stage. The plane flies once to the furthest stage you have reached.
function flightArt(reached) {
  const d = "M6 68 C 70 70, 110 16, 196 26 S 330 70, 414 14";
  return `<svg class="flight" viewBox="0 0 420 84" width="420" height="84" focusable="false"><title>Your search so far: stage ${reached + 1} of 5</title>
    <path class="fl-route" d="${d}"/><path class="fl-done" d="${d}"/>
    ${[0, 1, 2, 3, 4].map(i => `<g class="fl-wp${i <= reached ? " on" : ""}" data-i="${i}"><circle class="fl-hit" r="16"/><circle class="fl-ring" r="10"/><circle class="fl-stop" r="5"/></g>`).join("")}
    <g class="fl-plane"><path d="M-9 -6 L11 0 L-9 6 L-5 0 Z"/></g></svg>`;
}
function flyPlane(box, target) {
  const svg = box.querySelector(".flight"); if (!svg) return;
  const route = svg.querySelector(".fl-route"), done = svg.querySelector(".fl-done"), plane = svg.querySelector(".fl-plane"), L = route.getTotalLength();
  svg.querySelectorAll(".fl-wp").forEach((g, i) => { const p = route.getPointAtLength(L * i / 4); g.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`); });
  done.style.strokeDasharray = L;
  const at = t => { const s = Math.min(L - 1, L * t), p = route.getPointAtLength(s), q = route.getPointAtLength(s + 1);
    plane.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)}) rotate(${(Math.atan2(q.y - p.y, q.x - p.x) * 180 / Math.PI).toFixed(1)})`); done.style.strokeDashoffset = L * (1 - t); };
  if (!S.animate || reducedMotion()) return at(target);
  at(0); const t0 = performance.now();
  const tick = now => { const k = Math.min(1, (now - t0) / 1400); at(target * (1 - Math.pow(1 - k, 3))); if (k < 1 && document.contains(svg)) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}

// Numbers count up once when a page is opened (never on background refreshes, never with reduced motion).
function countUp(root) {
  if (!S.animate || reducedMotion()) return;
  root.querySelectorAll("[data-count]").forEach(el => {
    const to = +el.dataset.count; if (!(to > 0)) return;
    const t0 = performance.now(), dur = 650;
    const tick = t => { const p = Math.min(1, (t - t0) / dur); el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(tick); else el.textContent = to; };
    el.textContent = "0"; requestAnimationFrame(tick);
  });
}

// "6 of 8 requirements" as a two-part bar, for jobs that have been prepared.
function fitBar(r) {
  const a = r.adaptation; if (!a) return "";
  const have = (a.matched_requirements || []).length, miss = (a.missing_requirements || []).length, all = have + miss;
  if (!all) return "";
  return `<span class="fitbar" title="You cover ${have} of ${all} requirements"><span class="fb" aria-hidden="true"><i style="width:${Math.round(have / all * 100)}%"></i></span><span class="small muted">${have} of ${all} requirements</span></span>`;
}

// Three labelled bars explaining a match score.
function breakdownCard(b) {
  if (!b) return "";
  const row = (label, frac, note, cls = "") => `<div class="bdrow"><span class="bdl">${label}</span><span class="bdbar ${cls}" aria-hidden="true"><i style="width:${Math.round(Math.max(0, Math.min(1, frac)) * 100)}%"></i></span><span class="bdn">${note}</span></div>`;
  return `<section class="bdcard" aria-label="Why this score"><h4 style="margin:0 0 8px">Why this score</h4>
    ${b.skills == null ? row("Requirements", 0, "none listed in this posting", "na") : row("Requirements", b.skills, `${b.met} of ${b.asked} covered`)}
    ${row("Background fit", b.experience, b.experience >= .66 ? "close to your experience" : b.experience >= .4 ? "partly related" : "little overlap")}
    ${row("Location", b.location, b.location ? "fits your preferences" : esc(b.location_note || "outside your preferences"), b.location ? "" : "bad")}</section>`;
}

// ---- empty-state illustrations (theme tokens only, so they follow every theme)
const _ill = inner => `<svg viewBox="0 0 160 120" fill="none" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="80" cy="104" rx="52" ry="6" fill="var(--panel-2)"/>${inner}</svg>`;
Object.assign(EMPTY, {
  cards: _ill(`<rect x="34" y="30" width="66" height="44" rx="9" fill="var(--panel-2)" stroke="var(--line)" stroke-width="2" transform="rotate(-8 67 52)"/><rect x="50" y="42" width="70" height="48" rx="9" fill="var(--panel)" stroke="var(--line)" stroke-width="2"/>
    <rect x="60" y="53" width="14" height="14" rx="4" fill="var(--sky-bg)"/><path d="M82 57h26M82 65h16M60 78h48" stroke="var(--mute)" stroke-width="2"/><circle cx="118" cy="36" r="12" fill="var(--violet-bg)"/><path d="M118 31v10M113 36h10" stroke="var(--violet)" stroke-width="2.5"/>`),
  search: _ill(`<rect x="30" y="34" width="72" height="50" rx="9" fill="var(--panel)" stroke="var(--line)" stroke-width="2"/><path d="M42 48h34M42 58h46M42 68h22" stroke="var(--mute)" stroke-width="2"/>
    <circle cx="104" cy="62" r="18" fill="var(--sky-bg)" stroke="var(--sky)" stroke-width="2.5"/><path d="M117 76l12 12" stroke="var(--sky)" stroke-width="4"/><path d="M97 62l5 5 9-10" stroke="var(--sky)" stroke-width="2.5"/>`),
  interviews: _ill(`<rect x="34" y="30" width="68" height="60" rx="9" fill="var(--panel)" stroke="var(--line)" stroke-width="2"/><path d="M34 46h68" stroke="var(--line)" stroke-width="2"/><path d="M50 24v12M86 24v12" stroke="var(--mute)" stroke-width="3"/>
    <rect x="44" y="56" width="12" height="10" rx="3" fill="var(--panel-2)"/><rect x="62" y="56" width="12" height="10" rx="3" fill="var(--emerald-bg)" stroke="var(--emerald)" stroke-width="1.5"/><rect x="80" y="56" width="12" height="10" rx="3" fill="var(--panel-2)"/><rect x="44" y="72" width="12" height="10" rx="3" fill="var(--panel-2)"/>
    <path d="M96 64h32a6 6 0 0 1 6 6v16a6 6 0 0 1-6 6h-6l-7 7v-7h-19a6 6 0 0 1-6-6V70a6 6 0 0 1 6-6z" fill="var(--violet-bg)" stroke="var(--violet)" stroke-width="2"/><path d="M103 75h22M103 83h14" stroke="var(--violet)" stroke-width="2"/>`),
  outreach: _ill(`<rect x="26" y="46" width="64" height="44" rx="8" fill="var(--panel)" stroke="var(--line)" stroke-width="2"/><path d="M26 54l32 22 32-22" stroke="var(--mute)" stroke-width="2"/>
    <path d="M84 52l50-22-16 50-12-18z" fill="var(--sky-bg)" stroke="var(--sky)" stroke-width="2"/><path d="M106 62l28-32" stroke="var(--sky)" stroke-width="2"/><path d="M70 30c8-8 18-10 28-6" stroke="var(--mute)" stroke-width="2" stroke-dasharray="3 5"/>`),
  offers: _ill(`<rect x="44" y="24" width="60" height="72" rx="8" fill="var(--panel)" stroke="var(--line)" stroke-width="2"/><path d="M56 40h36M56 50h36M56 60h20" stroke="var(--mute)" stroke-width="2"/>
    <circle cx="100" cy="78" r="17" fill="var(--amber-bg)" stroke="var(--amber)" stroke-width="2"/><path d="M100 68l3 6.5 7 .8-5.2 4.8 1.5 7-6.3-3.6-6.3 3.6 1.5-7-5.2-4.8 7-.8z" fill="var(--amber)"/>`),
  practice: _ill(`<rect x="66" y="22" width="28" height="46" rx="14" fill="var(--violet-bg)" stroke="var(--violet)" stroke-width="2"/><path d="M54 56a26 26 0 0 0 52 0M80 82v12M66 94h28" stroke="var(--mute)" stroke-width="3"/>
    <path d="M36 44v14M28 48v6M124 44v14M132 48v6" stroke="var(--violet)" stroke-width="2.5"/>`),
  inbox: _ill(`<path d="M30 60l14-28h72l14 28v26a8 8 0 0 1-8 8H38a8 8 0 0 1-8-8z" fill="var(--panel)" stroke="var(--line)" stroke-width="2"/><path d="M30 60h30l6 10h28l6-10h30" stroke="var(--mute)" stroke-width="2"/>
    <circle cx="118" cy="32" r="13" fill="var(--emerald-bg)" stroke="var(--emerald)" stroke-width="2"/><path d="M112 32l4 4 8-9" stroke="var(--emerald)" stroke-width="2.5"/>`),
  done: _ill(`<circle cx="80" cy="56" r="34" fill="var(--emerald-bg)" stroke="var(--emerald)" stroke-width="2"/><path d="M65 57l10 10 21-23" stroke="var(--emerald)" stroke-width="5"/>
    <path d="M30 34l4 4M126 30l-4 4M24 70h6M130 74h6" stroke="var(--amber)" stroke-width="2.5"/>`),
});
