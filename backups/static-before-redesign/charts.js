"use strict";
/* Tiny SVG chart kit for the Insights view. Palette = validated reference palette (see app.css --series-*).
   Every chart: thin marks, 4px rounded data ends, 2px gaps, hover tooltip, legend when >= 2 series,
   selective direct labels, and a table view (required relief for low-contrast light-mode slots). */
const Charts = (() => {
  const e = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const S = n => `var(--series-${n})`;
  let tip;
  function tooltip() {
    if (!tip) { tip = document.createElement("div"); tip.className = "viz-tip"; tip.setAttribute("role", "tooltip"); document.body.append(tip); }
    return tip;
  }
  function bindTips(root) {
    root.querySelectorAll("[data-tip]").forEach(el => {
      const show = ev => { const t = tooltip(); t.innerHTML = el.dataset.tip; t.classList.add("on");
        const x = ev.clientX ?? el.getBoundingClientRect().left, y = ev.clientY ?? el.getBoundingClientRect().top;
        t.style.left = Math.min(innerWidth - t.offsetWidth - 12, x + 14) + "px"; t.style.top = Math.max(8, y - t.offsetHeight - 10) + "px"; };
      el.addEventListener("mousemove", show); el.addEventListener("focus", show);
      el.addEventListener("mouseleave", () => tooltip().classList.remove("on")); el.addEventListener("blur", () => tooltip().classList.remove("on"));
    });
  }
  const legend = items => `<div class="viz-legend">${items.map(([label, color]) => `<span><i style="background:${color}"></i>${e(label)}</span>`).join("")}</div>`;
  const table = (head, rows) => `<div class="viz-table" hidden><table><thead><tr>${head.map(h => `<th>${e(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${e(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  // 4px rounded data end, square at the baseline
  const barV = (x, y, w, h, r = 4) => h <= 0 ? "" : h < r ? `M${x},${y + h}V${y}H${x + w}V${y + h}Z` :
    `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  const barH = (x, y, w, h, r = 4) => w <= 0 ? "" : w < r ? `M${x},${y}H${x + w}V${y + h}H${x}Z` :
    `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;

  /** Horizontal bars; rows: [{label, value, color, note}] */
  const empty = msg => `<div class="empty" style="padding:30px 10px">${e(msg)}</div>`;
  function hbars(rows, { width = 560, unit = "", legendItems = null, emptyMsg = "No data yet" } = {}) {
    if (!rows.length) return empty(emptyMsg);
    const max = Math.max(1, ...rows.map(r => r.value)), rowH = 26, gap = 6, labelW = 150, pad = 36;
    const h = rows.length * (rowH + gap), plotW = width - labelW - pad;
    const svg = `<svg viewBox="0 0 ${width} ${h}" class="viz" role="img" aria-label="bar chart">
      ${rows.map((r, i) => { const y = i * (rowH + gap), w = Math.max(2, (r.value / max) * plotW);
        return `<g tabindex="0" data-tip="<b>${e(r.label)}</b><br>${r.value}${unit}${r.note ? " · " + e(r.note) : ""}" class="viz-hit">
          <text x="${labelW - 8}" y="${y + rowH / 2 + 4}" text-anchor="end" class="viz-lab">${e(r.label.length > 20 ? r.label.slice(0, 19) + "…" : r.label)}</text>
          <path d="${barH(labelW, y + 3, w, rowH - 6)}" fill="${r.color || S(1)}" class="viz-bar" style="--d:${i * 30}ms"/>
          <text x="${labelW + w + 6}" y="${y + rowH / 2 + 4}" class="viz-val">${r.value}${unit}</text>
          <rect x="0" y="${y}" width="${width}" height="${rowH}" fill="transparent"/></g>`; }).join("")}
    </svg>`;
    return (legendItems ? legend(legendItems) : "") + svg;
  }

  /** Vertical columns, single or grouped series. cats: labels; series: [{name, color, values[]}] */
  function columns(cats, series, { height = 200, width = 620, labelEvery = 1, showValues = false } = {}) {
    const max = Math.max(1, ...series.flatMap(s => s.values)), padL = 28, padB = 26, padT = 12;
    const plotW = width - padL - 8, plotH = height - padB - padT, groupW = plotW / cats.length;
    const gap = 2, barW = Math.max(3, Math.min(26, (groupW - 6) / series.length - gap));
    const ticks = [0, Math.ceil(max / 2), max];
    const y = v => padT + plotH - (v / max) * plotH;
    const svg = `<svg viewBox="0 0 ${width} ${height}" class="viz" role="img" aria-label="column chart">
      ${ticks.map(t => `<line x1="${padL}" x2="${width - 8}" y1="${y(t)}" y2="${y(t)}" class="viz-grid"/><text x="${padL - 6}" y="${y(t) + 4}" text-anchor="end" class="viz-axis">${t}</text>`).join("")}
      ${cats.map((c, i) => { const gx = padL + i * groupW + (groupW - series.length * (barW + gap)) / 2;
        const tipTxt = `<b>${e(c)}</b>` + series.map(s => `<br><i class="sw" style="background:${s.color}"></i>${e(s.name)}: ${s.values[i]}`).join("");
        return `<g tabindex="0" class="viz-hit" data-tip="${e(tipTxt)}">
          <rect x="${padL + i * groupW}" y="${padT}" width="${groupW}" height="${plotH}" fill="transparent"/>
          ${series.map((s, k) => { const v = s.values[i], bh = plotH - (y(v) - padT);
            return `<path d="${barV(gx + k * (barW + gap), y(v), barW, Math.max(0, bh))}" fill="${s.color}" class="viz-bar" style="--d:${i * 18}ms"/>
            ${showValues && v ? `<text x="${gx + k * (barW + gap) + barW / 2}" y="${y(v) - 5}" text-anchor="middle" class="viz-val">${v}</text>` : ""}`; }).join("")}
          ${i % labelEvery === 0 ? `<text x="${padL + i * groupW + groupW / 2}" y="${height - 8}" text-anchor="middle" class="viz-axis">${e(c)}</text>` : ""}</g>`; }).join("")}
      <line x1="${padL}" x2="${width - 8}" y1="${padT + plotH}" y2="${padT + plotH}" class="viz-base"/>
    </svg>`;
    return (series.length > 1 ? legend(series.map(s => [s.name, s.color])) : "") + svg;
  }

  /** Donut with 2px surface gaps; slices: [{label, value, color}] (caller folds past 6 into Other) */
  function donut(slices, { size = 200, center = "" } = {}) {
    if (!slices.length) return empty("No jobs yet — click Refresh jobs");
    const total = slices.reduce((a, s) => a + s.value, 0) || 1, R = size / 2 - 4, r = R * 0.62, cx = size / 2, cy = size / 2;
    let a0 = -Math.PI / 2;
    const arcs = slices.map((s, i) => {
      const frac = s.value / total, a1 = a0 + frac * Math.PI * 2, large = frac > 0.5 ? 1 : 0;
      const p = (rad, ang) => `${cx + rad * Math.cos(ang)},${cy + rad * Math.sin(ang)}`;
      const d = frac >= 0.999 ? `M${cx - R},${cy}A${R},${R} 0 1 1 ${cx + R},${cy}A${R},${R} 0 1 1 ${cx - R},${cy}M${cx - r},${cy}A${r},${r} 0 1 0 ${cx + r},${cy}A${r},${r} 0 1 0 ${cx - r},${cy}Z`
        : `M${p(R, a0)}A${R},${R} 0 ${large} 1 ${p(R, a1)}L${p(r, a1)}A${r},${r} 0 ${large} 0 ${p(r, a0)}Z`;
      a0 = a1;
      return `<path d="${d}" fill="${s.color}" class="viz-slice" tabindex="0" style="--d:${i * 60}ms" data-tip="<b>${e(s.label)}</b><br>${s.value} (${Math.round(frac * 100)}%)"/>`;
    }).join("");
    return `<div class="viz-donut"><svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" class="viz" role="img" aria-label="donut chart">${arcs}
      <text x="${cx}" y="${cy - 2}" text-anchor="middle" class="viz-center">${e(center)}</text><text x="${cx}" y="${cy + 16}" text-anchor="middle" class="viz-axis">jobs</text></svg>
      <div class="viz-legend vcol">${slices.map(s => `<span><i style="background:${s.color}"></i>${e(s.label)} <b>${s.value}</b></span>`).join("")}</div></div>`;
  }

  /** Funnel: ordinal single-hue steps, value + conversion labelled */
  function funnel(stages, { width = 560 } = {}) {
    const max = Math.max(1, stages[0].n), rowH = 38, gap = 6;   // bar length carries the value; one validated hue for every stage
    return `<svg viewBox="0 0 ${width} ${stages.length * (rowH + gap)}" class="viz" role="img" aria-label="application funnel">
      ${stages.map((s, i) => { const w = Math.max(4, (s.n / max) * (width - 170)), x = (width - 170 - w) / 2 + 80, y = i * (rowH + gap);
        const conv = i ? (stages[i - 1].n ? Math.round((s.n / stages[i - 1].n) * 100) + "% of previous" : "–") : "";
        return `<g tabindex="0" class="viz-hit" data-tip="<b>${e(s.stage)}</b><br>${s.n}${conv ? " · " + conv : ""}">
          <text x="72" y="${y + rowH / 2 + 4}" text-anchor="end" class="viz-lab">${e(s.stage)}</text>
          <rect x="${x}" y="${y}" width="${w}" height="${rowH}" rx="6" fill="var(--series-1)" class="viz-bar" style="--d:${i * 70}ms"/>
          <text x="${width - 84}" y="${y + rowH / 2 + 4}" class="viz-val"><tspan font-weight="700">${s.n}</tspan>${conv ? `<tspan class="viz-axis" dx="6">${conv.split(" ")[0]}</tspan>` : ""}</text></g>`; }).join("")}
    </svg>`;
  }

  /** Card wrapper with a Chart/Table toggle */
  function card(id, title, sub, body, tableHtml) {
    return `<section class="card viz-card" id="${id}"><div class="row"><div class="grow"><h3>${e(title)}</h3><p>${e(sub)}</p></div>
      <div class="seg viz-toggle"><button aria-pressed="true" data-vt="chart">Chart</button><button aria-pressed="false" data-vt="table">Table</button></div></div>
      <div class="viz-body">${body}</div>${tableHtml}</section>`;
  }
  function wire(root) {
    root.querySelectorAll(".viz-card").forEach(c => c.querySelectorAll("[data-vt]").forEach(b => b.onclick = () => {
      const t = b.dataset.vt === "table";
      c.querySelectorAll("[data-vt]").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
      c.querySelector(".viz-body").hidden = t; c.querySelector(".viz-table").hidden = !t;
    }));
    bindTips(root);
  }
  return { hbars, columns, donut, funnel, card, table, wire, S };
})();
