"use strict";
// Interaction layer: smooth page changes and Quick review (one job at a time, keyboard-first).
// Depends on app.js / toolkit.js / pro.js globals.

// ---- page changes cross-fade once (skipped with reduced motion or where the browser can't)
function smoothRender() {
  if (!document.startViewTransition || FX.level() === "off") return render();
  let done; const p = new Promise(r => done = r);
  const vt = document.startViewTransition(() => render().then(done, done));
  for (const k of ["ready", "finished", "updateCallbackDone"]) vt[k] && vt[k].catch(() => {});   // a newer page change replacing this one is fine
  return p;
}

// ---- Quick review: go through new matches one at a time
async function quickReview() {
  const queue = S.runs.filter(r => r.status === "scored" && (typeof matches !== "function" || matches(r))).sort((a, b) => (b.match_score || 0) - (a.match_score || 0));
  if (!queue.length) return toast("No new matches to review right now");
  let i = 0, undo = null, acted = false; const done = { prepared: 0, starred: 0, skipped: 0 };
  const m = modal("Quick review", `<div id="qr"></div>`, { wide: true });
  m.el.classList.add("qrmodal");
  const box = $("#qr", m.el);
  const finish = () => { box.innerHTML = `<div class="empty big" style="padding:30px 10px">${EMPTY.done}<b>That's all ${queue.length} new matches</b>
      <span>${done.prepared} being prepared · ${done.starred} starred · ${done.skipped} skipped</span><button class="btn primary" data-close>Done</button></div>`; $("[data-close]", box).focus(); };
  const draw = async () => {
    if (i >= queue.length) return finish();
    const r = queue[i], j = r.job;
    box.innerHTML = `<div class="qrbar" role="progressbar" aria-valuemin="0" aria-valuemax="${queue.length}" aria-valuenow="${i + 1}" aria-label="Job ${i + 1} of ${queue.length}"><i style="width:${((i + 1) / queue.length) * 100}%"></i></div>
      <div class="qrtop"><span class="small muted">${i + 1} of ${queue.length}</span><span class="grow"></span><span class="small muted">${done.prepared} prepared · ${done.starred} starred · ${done.skipped} skipped</span></div>
      <article class="qrcard" data-tilt="2.5" tabindex="-1" aria-live="polite">
        <header class="qrhead">${avatar(j.company, r.domain)}<div class="grow" style="min-width:0"><h3>${esc(j.title)}</h3><div class="jsub">${esc(j.company)}${j.location ? " · " + esc(j.location.slice(0, 50)) : ""}</div>
            <div class="meta">${r.salary ? `<span class="chip ok">${esc(r.salary.label)}</span>` : ""}${j.remote ? '<span class="chip info">Remote</span>' : ""}<span class="small muted">${src(j)} · ${esc(ago(r.created_at))}</span></div></div>${scoreRing(r.match_score)}</header>
        <div id="qrbody"><div class="sk" style="height:150px"></div></div></article>
      <div class="qractions">
        <button class="btn sm" id="qr-back" ${i ? "" : "disabled"}><kbd class="kbd">←</kbd> Back</button>
        <button class="btn sm" id="qr-skip"><kbd class="kbd">X</kbd> Not for me</button>
        <button class="btn sm" id="qr-star"><kbd class="kbd">S</kbd> ${r.starred ? "Starred ★" : "Star"}</button>
        <button class="btn sm" id="qr-open"><kbd class="kbd">O</kbd> Full details</button>
        <span class="grow"></span>
        <button class="btn sm" id="qr-next"><kbd class="kbd">→</kbd> Later</button>
        <button class="btn primary" id="qr-prep"><kbd class="kbd">P</kbd> Prepare application</button></div>
      <div class="row small muted qrhint">${undo ? `<button class="linkbtn" id="qr-undo">Undo “not for me” on ${esc(undo.job.title.slice(0, 40))}</button>` : "Use the keys shown, or click. Esc closes."}</div>`;
    // the card leaves the way the decision points: up and away when prepared, down when set aside, sideways when you move on
    const leave = async how => { const card = $(".qrcard", box); if (!card || !FX.moves()) return;
      const to = { up: "translate(36px,-44px) rotate(3deg)", down: "translate(-30px,40px) rotate(-3deg)", left: "translateX(-56px)", right: "translateX(56px)" }[how];
      const an = FX.anim(card, [{ transform: "none", opacity: 1 }, { transform: to, opacity: 0 }], { duration: 190, easing: "ease-in", fill: "forwards" }); if (an) await an.finished.catch(() => {});
      box.dataset.from = { up: "below", down: "below", left: "right", right: "left" }[how]; };
    const go_ = async n => { await leave(n > 0 ? "left" : "right"); i = Math.max(0, i + n); draw(); };
    $("#qr-back", box).onclick = () => go_(-1); $("#qr-next", box).onclick = () => go_(1);
    $("#qr-open", box).onclick = () => { m.close(); openDrawer(r.id); };
    $("#qr-star", box).onclick = async () => { try { await api(`/runs/${r.id}/note`, { method: "PUT", body: { starred: !r.starred } }); r.starred = !r.starred; if (r.starred) done.starred++; acted = true; go_(1); } catch (e) { toast(e.message); } };
    $("#qr-skip", box).onclick = async () => { try { await api(`/runs/${r.id}/dismiss`, { method: "POST" }); done.skipped++; undo = r; acted = true; await leave("down"); queue.splice(i, 1); draw(); } catch (e) { toast(e.message); } };
    $("#qr-prep", box).onclick = async () => { try { await api(`/runs/${r.id}/tailor`, { method: "POST" }); done.prepared++; acted = true; await leave("up"); queue.splice(i, 1); draw(); } catch (e) { toast(e.message); } };
    const u = $("#qr-undo", box); if (u) u.onclick = async () => { try { await api(`/runs/${undo.id}/restore`, { method: "POST" }); queue.splice(i, 0, undo); done.skipped--; undo = null; draw(); } catch (e) { toast(e.message); } };
    $(".qrcard", box).focus({ preventScroll: true });
    try {
      const d = await api("/runs/" + r.id); if (queue[i] !== r) return;
      const k = d.keywords || { have: [], missing: [] };
      $("#qrbody", box).innerHTML = `${verdictCard(d.verdict)}
        <div class="qrkw">${k.have.length ? `<div><h5>You have</h5><div class="row" style="gap:6px">${k.have.slice(0, 8).map(x => `<span class="chip ok">${esc(x.term)}</span>`).join("")}</div></div>` : ""}
          ${k.missing.length ? `<div><h5>Missing</h5><div class="row" style="gap:6px">${k.missing.slice(0, 8).map(x => `<span class="chip miss">${esc(x.term)}</span>`).join("")}</div></div>` : ""}</div>
        <p class="qrdesc">${esc((d.job.description || "").replace(/\s+/g, " ").slice(0, 420))}${(d.job.description || "").length > 420 ? "…" : ""}</p>`;
    } catch { const b = $("#qrbody", box); if (b) b.innerHTML = `<p class="small muted">Couldn't load the details. You can still decide, or open the full details.</p>`; }
  };
  m.el.addEventListener("keydown", e => {
    if (e.target.matches("input,textarea,select") || e.metaKey || e.ctrlKey || e.altKey) return;
    const id = { ArrowLeft: "#qr-back", ArrowRight: "#qr-next", x: "#qr-skip", s: "#qr-star", p: "#qr-prep", o: "#qr-open", k: "#qr-back", j: "#qr-next" }[e.key.length === 1 ? e.key.toLowerCase() : e.key];
    const b = id && $(id, box); if (b && !b.disabled) { e.preventDefault(); e.stopPropagation(); b.click(); }
  });
  const obs = new MutationObserver(() => { if (!document.body.contains(m.el)) { obs.disconnect(); if (acted) render(); } });   // refresh the list once it closes
  obs.observe(document.body, { childList: true });
  draw();
}
