"use strict";
/* Effects layer, shared by the app and the landing page. No dependencies: CSS does the drawing, this file only
   feeds it positions and starts one-off animations.

   Three levels, read from <html>:
     full  ambient light, cursor effects, transitions            (default)
     calm  transitions only: nothing follows the pointer, nothing loops
     off   reduced motion (the setting, or the system preference)

   Everything here is safe to call at any level; each function checks before it moves anything. */
const FX = (() => {
  const root = document.documentElement;
  const mqReduce = matchMedia("(prefers-reduced-motion: reduce)"), mqFine = matchMedia("(hover: hover) and (pointer: fine)");
  const level = () => root.dataset.motion === "reduce" || mqReduce.matches ? "off" : root.dataset.fx === "calm" ? "calm" : "full";
  const full = () => level() === "full", moves = () => level() !== "off";
  const GLIDE = "cubic-bezier(.2,.7,.2,1)", SETTLE = "cubic-bezier(.3,1.4,.5,1)";
  const anim = (el, frames, opts) => { try { return el.animate(frames, opts); } catch { return null; } };

  // ---------------------------------------------------------------- the pointer: light, tilt, pull
  // One listener for the whole page. Each frame it updates, at most, the card under the pointer.
  let cfg = { spot: "", tilt: "", magnet: "" }, last = null, queued = false, tiltEl = null, magEl = null, bound = false;
  const clear = (el, names) => el && names.forEach(n => el.style.removeProperty(n));
  function frame() {
    queued = false;
    const e = last, t = e && e.target instanceof Element ? e.target : null;
    if (!t || !full() || !mqFine.matches) return release();
    if (cfg.spot) {
      const s = t.closest(cfg.spot);
      if (s) { const r = s.getBoundingClientRect(); s.style.setProperty("--mx", Math.round(e.clientX - r.left) + "px"); s.style.setProperty("--my", Math.round(e.clientY - r.top) + "px"); }
    }
    const tl = cfg.tilt ? t.closest(cfg.tilt) : null;
    if (tl !== tiltEl) { clear(tiltEl, ["--rx", "--ry"]); tiltEl = tl; }
    if (tl) {
      const r = tl.getBoundingClientRect(), max = +tl.dataset.tilt || 5;
      tl.style.setProperty("--ry", (((e.clientX - r.left) / r.width - .5) * max).toFixed(2) + "deg");
      tl.style.setProperty("--rx", ((.5 - (e.clientY - r.top) / r.height) * max).toFixed(2) + "deg");
    }
    const mg = cfg.magnet ? t.closest(cfg.magnet) : null;
    if (mg !== magEl) { clear(magEl, ["--tx", "--ty"]); magEl = mg; }
    if (mg && !mg.disabled) {
      const r = mg.getBoundingClientRect();
      mg.style.setProperty("--tx", ((e.clientX - r.left - r.width / 2) * .2).toFixed(1) + "px");
      mg.style.setProperty("--ty", ((e.clientY - r.top - r.height / 2) * .3).toFixed(1) + "px");
    }
  }
  function release() { clear(tiltEl, ["--rx", "--ry"]); clear(magEl, ["--tx", "--ty"]); tiltEl = magEl = null; }
  function pointer(selectors) {
    cfg = { ...cfg, ...selectors };
    if (bound) return; bound = true;
    addEventListener("pointermove", e => { if (e.pointerType === "touch") return; last = e; if (!queued) { queued = true; requestAnimationFrame(frame); } }, { passive: true });
    document.addEventListener("pointerleave", () => { last = null; release(); });
    addEventListener("blur", release);
  }

  // ---------------------------------------------------------------- one-off animations
  // A heading arrives: it rises, and the typeface opens out from narrow to its full width.
  function title(el) {
    if (!el || !moves()) return;
    const cs = getComputedStyle(el);
    anim(el, [{ opacity: 0, transform: "translateY(8px)", fontStretch: "82%" }, { opacity: 1, transform: "none", fontStretch: cs.fontStretch }], { duration: 480, easing: GLIDE });
  }
  // A number changed: a small pop so the eye catches it.
  const bump = el => { if (el && moves()) anim(el, [{ transform: "scale(1)" }, { transform: "scale(1.4)" }, { transform: "scale(1)" }], { duration: 420, easing: SETTLE }); };

  // The marker in the sidebar glides to the current page instead of jumping.
  function glide() {
    const side = document.getElementById("side"); if (!side) return;
    let g = side.querySelector(".navglide"), fresh = false;
    if (!g) { g = document.createElement("i"); g.className = "navglide"; g.setAttribute("aria-hidden", "true"); side.prepend(g); fresh = true; }
    const cur = side.querySelector(".nav[aria-current=page]");
    if (fresh || !moves()) g.style.transition = "none";
    if (cur) side.style.setProperty("--gy", cur.offsetTop + "px");
    side.classList.toggle("glide", !!cur);
    if (g.style.transition) { void g.offsetWidth; g.style.transition = ""; }
  }

  // The underline of a tab row slides from the tab you left to the one you chose.
  const lastTab = new Map();
  function tabs(scope) {
    (scope || document).querySelectorAll(".tabsbar").forEach(bar => {
      const sel = bar.querySelector('[role=tab][aria-selected="true"]'); let ink = bar.querySelector(".tabink");
      if (!sel || !sel.offsetWidth) { if (ink) ink.remove(); bar.classList.remove("inked"); return; }
      const key = bar.getAttribute("aria-label") || "tabs", x = sel.offsetLeft + 10, w = Math.max(8, sel.offsetWidth - 20), at = x + ":" + w;
      if (ink && ink.dataset.at === at) return;
      if (!ink) { ink = document.createElement("i"); ink.className = "tabink"; ink.setAttribute("aria-hidden", "true"); bar.append(ink); }
      const prev = lastTab.get(key);
      ink.style.width = w + "px"; ink.style.transform = `translateX(${x}px)`; ink.dataset.at = at; bar.classList.add("inked");
      if (prev && moves() && (prev.x !== x || prev.w !== w))
        anim(ink, [{ transform: `translateX(${prev.x}px)`, width: prev.w + "px" }, { transform: `translateX(${x}px)`, width: w + "px" }], { duration: 340, easing: GLIDE });
      lastTab.set(key, { x, w });
    });
  }

  // Content further down the page waits until it is scrolled into view.
  let io = null;
  function reveal(scope, selector, everything = false) {
    if (!moves() || !("IntersectionObserver" in window)) return;
    io = io || new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -6% 0px", threshold: .06 });
    (scope || document).querySelectorAll(selector).forEach(el => {
      if (el.classList.contains("rv")) return;
      const r = el.getBoundingClientRect();
      if (!r.height || (!everything && r.top < innerHeight * .94)) return;      // already on screen: it has its own entrance
      el.classList.add("rv"); io.observe(el);
    });
  }
  // nothing may stay hidden: anything you tab into, or search for, is shown at once
  document.addEventListener("focusin", e => { const h = e.target.closest && e.target.closest(".rv:not(.in)"); if (h) h.classList.add("in"); });

  // A piece of text travels from where it was (a table row) to where it now lives (the page title).
  function flyText(from, to, hold) {
    if (!moves() || !from || !to) return false;
    const a = from.getBoundingClientRect(), b = to.getBoundingClientRect();
    if (!a.width || !b.width || a.bottom < 0 || a.top > innerHeight) return false;
    const cs = getComputedStyle(to), g = document.createElement("div"), s = parseFloat(getComputedStyle(from).fontSize) / parseFloat(cs.fontSize);
    g.className = "fx-ghost"; g.textContent = to.textContent; g.setAttribute("aria-hidden", "true");
    Object.assign(g.style, { left: b.left + "px", top: b.top + "px", width: b.width + "px", font: cs.font, fontStretch: cs.fontStretch, letterSpacing: cs.letterSpacing, color: cs.color });
    document.body.append(g); if (hold) hold(true);
    const done = () => { g.remove(); if (hold) hold(false); };
    const an = anim(g, [{ transform: `translate(${a.left - b.left}px, ${a.top - b.top}px) scale(${s})`, opacity: .9 }, { transform: "none", opacity: 1 }], { duration: 420, easing: GLIDE });
    if (!an) return done(), false;
    an.finished.then(done, done);
    return true;
  }

  // A number that changed counts from the old value to the new one, easing to a stop.
  function tween(el, from, to, dur = 900) {
    if (!moves()) { el.textContent = to; return; }
    const t0 = performance.now(); el.classList.add("ticking");
    const tick = t => { const p = Math.min(1, (t - t0) / dur), k = 1 - Math.pow(1 - p, 4); el.textContent = Math.round(from + (to - from) * k);
      if (p < 1) requestAnimationFrame(tick); else { el.textContent = to; el.classList.remove("ticking"); bump(el); } };
    requestAnimationFrame(tick);
  }
  // A figure counts to its value once (data-to, optional data-from / data-suffix).
  function counter(el) {
    const to = +el.dataset.to, from = +(el.dataset.from || 0), suf = el.dataset.suffix || "";
    if (!moves() || !isFinite(to)) { el.textContent = to + suf; return; }
    const t0 = performance.now(), dur = 1100;
    const tick = t => { const p = Math.min(1, (t - t0) / dur), k = 1 - Math.pow(1 - p, 4); el.textContent = Math.round(from + (to - from) * k) + suf; if (p < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------- the app: keep the moving parts in step with the page
  function watch(main) {
    if (!main || !("MutationObserver" in window)) return;
    let due = false;
    const run = () => { due = false; tabs(main); const c = main.querySelector(".content"); if (c && !c.classList.contains("noanim")) reveal(c, ".view > .viz-card, .insights > *, .helpgrid > *, .settings > .sec, .intel > *"); };
    new MutationObserver(() => { if (!due) { due = true; requestAnimationFrame(run); } }).observe(main, { childList: true, subtree: true });
    let wide = innerWidth; addEventListener("resize", () => { if (innerWidth !== wide) { wide = innerWidth; lastTab.clear(); main.querySelectorAll(".tabink").forEach(i => delete i.dataset.at); tabs(main); glide(); } }, { passive: true });
    run();
  }
  // the top bar knows when the page has moved under it
  function scrollAware() {
    let was = false;
    const check = () => { const now = scrollY > 6; if (now !== was) { was = now; root.classList.toggle("scrolled", now); } };
    addEventListener("scroll", check, { passive: true }); check();
  }
  // first paint: the frame assembles once (bar, then the sidebar items in turn)
  function boot() { if (!moves()) return; root.classList.add("boot"); setTimeout(() => root.classList.remove("boot"), 1400); }

  // ---------------------------------------------------------------- landing page: the night sky
  // Waypoints and a few routes being flown. Draws only while it is on screen and the tab is visible.
  function sky(cv, o = {}) {
    const ctx = cv.getContext && cv.getContext("2d"); if (!ctx) return null;
    let W = 0, H = 0, pts = [], routes = [], px = 0, py = 0, tx = 0, ty = 0, raf = 0, seen = true, prev = 0, mx = -1e4, my = -1e4;
    let seedN = o.seed || 11; const rnd = () => (seedN = (seedN * 1664525 + 1013904223) % 4294967296) / 4294967296;
    const host = o.host || cv.parentElement;
    function route(t) {
      const a = pts[(rnd() * pts.length) | 0]; let b = a, n = 0;
      while ((b === a || Math.abs(b.x - a.x) < W * .16) && n++ < 24) b = pts[(rnd() * pts.length) | 0];
      return { a, b, t: t || 0, v: .045 + rnd() * .05, lift: (.1 + rnd() * .2) * (rnd() < .5 ? -1 : 1), land: 0 };
    }
    function size() {
      const r = cv.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
      if (!r.width || (Math.round(r.width) === W && Math.round(r.height) === H)) return;
      W = Math.round(r.width); H = Math.round(r.height); cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seedN = o.seed || 11;
      pts = Array.from({ length: Math.round(Math.min(64, Math.max(22, W * H / 24000))) }, () => ({ x: rnd() * W, y: rnd() * H * .94, z: .3 + rnd() * .7, r: .7 + rnd() * 1.2, p: rnd() * 6.28 }));
      routes = Array.from({ length: W < 720 ? 3 : 6 }, (_, i) => route(i / 6 + rnd() * .3));
      draw(performance.now(), true);
    }
    const at = (r, t, ox, oy) => {                 // a point on the arc from a to b, bowed by `lift`
      const ax = r.a.x + ox * r.a.z, ay = r.a.y + oy * r.a.z, bx = r.b.x + ox * r.b.z, by = r.b.y + oy * r.b.z;
      const cx = (ax + bx) / 2 - (by - ay) * r.lift, cy = (ay + by) / 2 + (bx - ax) * r.lift, u = 1 - t;
      return [u * u * ax + 2 * u * t * cx + t * t * bx, u * u * ay + 2 * u * t * cy + t * t * by];
    };
    function draw(now, still) {
      const dt = Math.min(.05, (now - prev) / 1000 || 0); prev = now;
      px += (tx - px) * .06; py += (ty - py) * .06;
      const ox = -px * 26, oy = -py * 16, T = now / 1000;
      ctx.clearRect(0, 0, W, H);
      for (const p of pts) {                        // waypoints: nearer ones are larger and move more; they wake near the pointer
        const x = p.x + ox * p.z, y = p.y + oy * p.z, d = Math.hypot(x - mx, y - my), near = d < 170 ? 1 - d / 170 : 0;
        ctx.globalAlpha = Math.min(1, (.16 + .2 * p.z) * (still ? 1 : .75 + .25 * Math.sin(T * .7 + p.p)) + near * .55);
        ctx.fillStyle = near > .05 ? "#CFE4FF" : "#9DB8FF"; ctx.beginPath(); ctx.arc(x, y, p.r * (.7 + p.z * .6) + near * 1.2, 0, 6.2832); ctx.fill();
      }
      ctx.lineCap = "round";
      routes.forEach((r, i) => {
        if (!still) r.t += r.v * dt;
        const head = Math.min(1, r.t), tail = Math.max(0, head - .5), N = 22;
        for (let k = 0; k < N; k++) {                // the trail fades toward where it started
          const t1 = tail + (head - tail) * k / N, t2 = tail + (head - tail) * (k + 1) / N, [x1, y1] = at(r, t1, ox, oy), [x2, y2] = at(r, t2, ox, oy);
          ctx.globalAlpha = .4 * Math.pow((k + 1) / N, 1.6) * (r.t > 1 ? Math.max(0, 1 - (r.t - 1) * 4) : 1);
          ctx.strokeStyle = k > N - 5 ? "#F5B301" : "#7CC4FF"; ctx.lineWidth = 1.1; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
        }
        const [hx, hy] = at(r, head, ox, oy);
        if (r.t <= 1) { ctx.globalAlpha = .95; ctx.fillStyle = "#FFD45A"; ctx.beginPath(); ctx.arc(hx, hy, 1.9, 0, 6.2832); ctx.fill(); }
        else {                                       // arrival: one ring, then a new route elsewhere
          const k = (r.t - 1) * 3.2;
          if (k < 1) { ctx.globalAlpha = (1 - k) * .7; ctx.strokeStyle = "#F5B301"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(hx, hy, 3 + k * 16, 0, 6.2832); ctx.stroke(); }
          else routes[i] = route(0);
        }
      });
      ctx.globalAlpha = 1;
    }
    const loop = now => { raf = 0; if (!seen || document.hidden || !full()) return; draw(now); raf = requestAnimationFrame(loop); };
    const start = () => { if (!raf && seen && !document.hidden && full()) { prev = performance.now(); raf = requestAnimationFrame(loop); } };
    host.addEventListener("pointermove", e => { if (e.pointerType === "touch") return; const r = host.getBoundingClientRect(); tx = (e.clientX - r.left) / r.width - .5; ty = (e.clientY - r.top) / r.height - .5;
      const c = cv.getBoundingClientRect(); mx = e.clientX - c.left; my = e.clientY - c.top; }, { passive: true });
    host.addEventListener("pointerleave", () => { tx = ty = 0; mx = my = -1e4; });
    if ("IntersectionObserver" in window) new IntersectionObserver(es => { seen = es[0].isIntersecting; start(); }).observe(cv);
    document.addEventListener("visibilitychange", start);
    if ("ResizeObserver" in window) new ResizeObserver(size).observe(cv); else addEventListener("resize", size);
    size(); start();
    return { start, redraw: () => draw(performance.now(), !full()) };
  }

  return { level, full, moves, pointer, title, bump, tween, glide, tabs, reveal, flyText, counter, watch, scrollAware, boot, sky, anim, GLIDE, SETTLE };
})();
