"use strict";

const AXES = [
  { key: "vx_forward_m_s", label: "vx forward", color: "#2463eb" },
  { key: "vy_left_m_s", label: "vy left", color: "#d95d1f" },
  { key: "vz_up_m_s", label: "vz up", color: "#7c3aed" },
];

const stateColors = {
  ARM: "#dfe5e1", MANUAL: "#f4e8bd", TAKEOFF: "#cce0f5",
  ALT_HOLD: "#cfe8dc", TRACK: "#f4d7b7", FAILSAFE: "#efc8c3",
};

const state = { summary: null, velocity: null, view: null, dragStart: null, scopeEnd: null };
const el = (id) => document.getElementById(id);

async function requestJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  let body = null;
  try { body = await response.json(); } catch (_) { body = null; }
  if (!response.ok) throw new Error(body?.detail || `${response.status} ${response.statusText}`);
  return body;
}

function formatNumber(value, digits = 2, suffix = "") {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(digits)}${suffix}`;
}

function formatUtc(nanoseconds) {
  if (!nanoseconds) return "Unknown start time";
  return new Date(Number(nanoseconds) / 1e6).toLocaleString();
}

function addCard(label, value, detail) {
  const card = document.createElement("article");
  card.className = "card";
  for (const [className, text] of [["card-label", label], ["card-value", value], ["card-detail", detail]]) {
    const node = document.createElement(className === "card-value" ? "p" : "div");
    node.className = className;
    node.textContent = text;
    card.append(node);
  }
  el("summary-cards").append(card);
}

function addMetric(label, value) {
  const term = document.createElement("dt"); term.textContent = label;
  const description = document.createElement("dd"); description.textContent = value;
  el("quality-list").append(term, description);
}

function visibleIntervals() {
  if (!state.summary) return [];
  if (state.scopeEnd === null) return state.summary.states;
  return state.summary.states
    .filter((interval) => interval.start_s <= state.scopeEnd)
    .map((interval) => ({
      ...interval,
      end_s: Math.min(interval.end_s, state.scopeEnd),
      duration_s: Math.max(0, Math.min(interval.end_s, state.scopeEnd) - interval.start_s),
    }))
    .filter((interval) => interval.duration_s > 0);
}

function filteredVelocityStatistics() {
  if (!state.velocity) return null;
  const indices = state.velocity.elapsed_s
    .map((time, index) => ({ time, index }))
    .filter(({ time }) => state.scopeEnd === null || time <= state.scopeEnd);
  if (!indices.length) return null;
  return Object.fromEntries(AXES.map((axis) => {
    const samples = indices.map(({ time, index }) => ({ time, value: state.velocity[axis.key][index] }));
    const squareMean = samples.reduce((sum, sample) => sum + sample.value ** 2, 0) / samples.length;
    const minimum = samples.reduce((best, sample) => sample.value < best.value ? sample : best);
    const maximum = samples.reduce((best, sample) => sample.value > best.value ? sample : best);
    return [axis.key, {
      mean_m_s: samples.reduce((sum, sample) => sum + sample.value, 0) / samples.length,
      rms_m_s: Math.sqrt(squareMean),
      min: { value_m_s: minimum.value, elapsed_s: minimum.time },
      max: { value_m_s: maximum.value, elapsed_s: maximum.time },
    }];
  }));
}

function renderScopedData() {
  const intervals = visibleIntervals();
  el("state-table").replaceChildren();
  for (const interval of intervals) {
    const row = document.createElement("tr");
    for (const value of [interval.state, formatNumber(interval.start_s, 2, " s"), formatNumber(interval.duration_s, 2, " s")]) {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    }
    el("state-table").append(row);
  }
  renderStateLegend(intervals);
  renderVelocityStatistics(filteredVelocityStatistics() || state.summary.velocity.statistics);
}

function renderSummary(summary) {
  const session = summary.session;
  const quality = summary.quality;
  el("session-subtitle").textContent = `${session.session_id} · ${formatUtc(session.start_utc_ns)}`;
  el("status-pill").textContent = `${session.status} · ${session.end_reason || "unknown end"}`;
  el("summary-cards").replaceChildren();
  addCard("Duration", formatNumber(session.duration_s, 2, " s"), `${summary.states.length} state intervals`);
  addCard("Control frames", quality.frame_count.toLocaleString(), `${formatNumber(quality.frame_rate_hz, 2, " Hz")}`);
  addCard("Odometry", quality.odometry_count.toLocaleString(), `${formatNumber(quality.odometry_rate_hz, 2, " Hz")}`);
  addCard("Schema", `v${session.schema_version ?? "—"}`, session.git_revision ? session.git_revision.slice(0, 10) : "No Git revision");

  el("quality-list").replaceChildren();
  addMetric("Dropped control frames", quality.dropped_frames.toLocaleString());
  addMetric("Dropped odometry", quality.dropped_odometry.toLocaleString());
  addMetric("Writer errors", quality.writer_errors.toLocaleString());
  addMetric("Application version", session.app_version || "—");
  addMetric("Log timezone", session.timezone || "—");

  renderScopedData();
}

function renderStateLegend(intervals) {
  const legend = el("chart-legend");
  legend.replaceChildren();
  const states = [...new Set(intervals.map((interval) => interval.state))];
  for (const stateName of states) {
    const item = document.createElement("span"); item.className = "legend-item";
    const swatch = document.createElement("span"); swatch.className = "legend-swatch";
    swatch.style.backgroundColor = stateColors[stateName] || "#e8ebe8";
    const label = document.createElement("span"); label.textContent = stateName;
    item.append(swatch, label); legend.append(item);
  }
}

function renderVelocityStatistics(statistics) {
  const container = el("velocity-stats");
  container.replaceChildren();
  if (!statistics) return;
  for (const axis of AXES) {
    const stats = statistics[axis.key];
    if (!stats) continue;
    const card = document.createElement("article");
    card.className = "panel axis-card";
    card.style.setProperty("--axis-color", axis.color);
    const title = document.createElement("h3"); title.textContent = axis.label;
    const grid = document.createElement("div"); grid.className = "axis-grid";
    const values = [
      ["Mean", formatNumber(stats.mean_m_s, 3, " m/s")],
      ["RMS", formatNumber(stats.rms_m_s, 3, " m/s")],
      ["Minimum", `${formatNumber(stats.min.value_m_s, 3)} @ ${formatNumber(stats.min.elapsed_s, 2, " s")}`],
      ["Maximum", `${formatNumber(stats.max.value_m_s, 3)} @ ${formatNumber(stats.max.elapsed_s, 2, " s")}`],
    ];
    for (const [label, value] of values) {
      const item = document.createElement("div"); item.className = "axis-stat";
      const caption = document.createElement("span"); caption.textContent = label;
      const strong = document.createElement("strong"); strong.textContent = value;
      item.append(caption, strong); grid.append(item);
    }
    card.append(title, grid); container.append(card);
  }
}

function svgNode(name, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function nearestIndex(values, target) {
  let low = 0, high = values.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (values[mid] < target) low = mid + 1; else high = mid;
  }
  if (low > 0 && Math.abs(values[low - 1] - target) < Math.abs(values[low] - target)) return low - 1;
  return low;
}

function renderChart() {
  if (!state.velocity || !state.velocity.elapsed_s.length) return;
  const container = el("chart");
  const width = Math.max(680, container.clientWidth || 1100);
  const height = container.clientHeight || 650;
  const margin = { left: 76, right: 24, top: 16, bottom: 38 };
  const gap = 26;
  const panelHeight = (height - margin.top - margin.bottom - gap * 2) / 3;
  const plotWidth = width - margin.left - margin.right;
  const [viewStart, viewEnd] = state.view;
  const times = state.velocity.elapsed_s;
  const x = (value) => margin.left + (value - viewStart) / (viewEnd - viewStart) * plotWidth;
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none" });

  const limits = AXES.map((axis) => {
    const values = state.velocity[axis.key];
    let peak = 0.1;
    for (let i = 0; i < times.length; i++) if (times[i] >= viewStart && times[i] <= viewEnd) peak = Math.max(peak, Math.abs(values[i]));
    return peak * 1.1;
  });

  AXES.forEach((axis, panelIndex) => {
    const panelTop = margin.top + panelIndex * (panelHeight + gap);
    const limit = limits[panelIndex];
    const y = (value) => panelTop + (limit - value) / (2 * limit) * panelHeight;
    for (const interval of visibleIntervals()) {
      const start = Math.max(interval.start_s, viewStart), end = Math.min(interval.end_s, viewEnd);
      if (end <= start) continue;
      svg.append(svgNode("rect", { x: x(start), y: panelTop, width: x(end) - x(start), height: panelHeight, fill: stateColors[interval.state] || "#e8ebe8", opacity: ".62" }));
    }
    for (const fraction of [-1, -.5, 0, .5, 1]) {
      const value = fraction * limit;
      svg.append(svgNode("line", { x1: margin.left, y1: y(value), x2: width - margin.right, y2: y(value), stroke: fraction === 0 ? "#718078" : "#d9ded9", "stroke-width": fraction === 0 ? 1.2 : 1 }));
      const label = svgNode("text", { x: margin.left - 10, y: y(value) + 4, "text-anchor": "end", fill: "#617068", "font-size": 11 });
      label.textContent = value.toFixed(2); svg.append(label);
    }
    const axisLabel = svgNode("text", { x: margin.left + 8, y: panelTop + 18, fill: axis.color, "font-size": 13, "font-weight": 750 });
    axisLabel.textContent = axis.label; svg.append(axisLabel);
    const values = state.velocity[axis.key];
    let path = "";
    for (let i = 0; i < times.length; i++) {
      if (times[i] < viewStart || times[i] > viewEnd) continue;
      path += `${path ? "L" : "M"}${x(times[i]).toFixed(2)},${y(values[i]).toFixed(2)}`;
    }
    svg.append(svgNode("path", { d: path, fill: "none", stroke: axis.color, "stroke-width": 1.6, "vector-effect": "non-scaling-stroke" }));
    svg.append(svgNode("rect", { x: margin.left, y: panelTop, width: plotWidth, height: panelHeight, fill: "none", stroke: "#8b9890" }));
  });

  const tickCount = Math.max(3, Math.min(10, Math.floor(plotWidth / 100)));
  for (let i = 0; i <= tickCount; i++) {
    const value = viewStart + (viewEnd - viewStart) * i / tickCount;
    const label = svgNode("text", { x: x(value), y: height - 12, "text-anchor": "middle", fill: "#617068", "font-size": 11 });
    label.textContent = value.toFixed(1); svg.append(label);
  }
  const cursor = svgNode("line", { y1: margin.top, y2: height - margin.bottom, stroke: "#17211c", "stroke-width": 1, "stroke-dasharray": "4 4", visibility: "hidden" });
  const selection = svgNode("rect", { y: margin.top, height: height - margin.top - margin.bottom, fill: "#0b7351", opacity: ".13", visibility: "hidden" });
  const overlay = svgNode("rect", { x: margin.left, y: margin.top, width: plotWidth, height: height - margin.top - margin.bottom, fill: "transparent", cursor: "crosshair" });
  svg.append(cursor, selection, overlay);
  container.replaceChildren(svg);

  const eventTime = (event) => {
    const bounds = svg.getBoundingClientRect();
    const pixel = Math.max(margin.left, Math.min(width - margin.right, (event.clientX - bounds.left) * width / bounds.width));
    return viewStart + (pixel - margin.left) / plotWidth * (viewEnd - viewStart);
  };
  overlay.addEventListener("pointermove", (event) => {
    const time = eventTime(event); const index = nearestIndex(times, time); const cx = x(times[index]);
    cursor.setAttribute("x1", cx); cursor.setAttribute("x2", cx); cursor.setAttribute("visibility", "visible");
    const tooltip = el("chart-tooltip");
    tooltip.textContent = `${times[index].toFixed(3)} s  ·  forward ${state.velocity.vx_forward_m_s[index].toFixed(3)}  ·  left ${state.velocity.vy_left_m_s[index].toFixed(3)}  ·  up ${state.velocity.vz_up_m_s[index].toFixed(3)} m/s`;
    tooltip.hidden = false;
    const panelBounds = el("chart-panel").getBoundingClientRect();
    tooltip.style.left = `${Math.min(event.clientX - panelBounds.left + 14, panelBounds.width - 245)}px`;
    tooltip.style.top = `${Math.max(8, event.clientY - panelBounds.top - 45)}px`;
    if (state.dragStart !== null) {
      const startX = x(state.dragStart), endX = x(time);
      selection.setAttribute("x", Math.min(startX, endX)); selection.setAttribute("width", Math.abs(endX - startX)); selection.setAttribute("visibility", "visible");
    }
  });
  overlay.addEventListener("pointerleave", () => { if (state.dragStart === null) { cursor.setAttribute("visibility", "hidden"); el("chart-tooltip").hidden = true; } });
  overlay.addEventListener("pointerdown", (event) => { state.dragStart = eventTime(event); overlay.setPointerCapture(event.pointerId); });
  overlay.addEventListener("pointerup", (event) => {
    if (state.dragStart === null) return;
    const end = eventTime(event), start = state.dragStart; state.dragStart = null;
    if (Math.abs(end - start) > (viewEnd - viewStart) * .01) {
      state.view = [Math.min(start, end), Math.max(start, end)]; el("reset-zoom").disabled = false; renderChart();
    } else selection.setAttribute("visibility", "hidden");
  });
}

async function loadDashboard() {
  el("loading").hidden = false; el("error").hidden = true; el("content").hidden = true;
  try {
    const summary = await requestJson("/api/latest");
    state.summary = summary; state.scopeEnd = null; el("data-scope").value = "all"; renderSummary(summary);
    if (summary.velocity.available) {
      state.velocity = await requestJson(`/api/sessions/${encodeURIComponent(summary.session.session_id)}/velocity`);
      const times = state.velocity.elapsed_s;
      state.view = [times[0], times[times.length - 1]];
      const hasTrack = summary.states.some((interval) => interval.state === "TRACK");
      el("data-scope").disabled = !hasTrack;
      el("velocity-unavailable").hidden = true; el("chart-panel").hidden = false; el("reset-zoom").disabled = true;
    } else {
      state.velocity = null; el("chart-panel").hidden = true; el("velocity-unavailable").hidden = false;
      el("velocity-unavailable").textContent = "This session has no schema-v2 odometry stream. Metadata and state statistics remain available.";
    }
    el("loading").hidden = true; el("content").hidden = false;
    if (state.velocity) requestAnimationFrame(renderChart);
  } catch (error) {
    el("loading").hidden = true; el("error").hidden = false;
    el("error-title").textContent = "Unable to load the latest flight";
    el("error-detail").textContent = error.message;
  }
}

el("reload").addEventListener("click", loadDashboard);
el("retry").addEventListener("click", loadDashboard);
el("data-scope").addEventListener("change", (event) => {
  if (!state.velocity) return;
  const trackIntervals = state.summary.states.filter((interval) => interval.state === "TRACK");
  state.scopeEnd = event.target.value === "through-track"
    ? Math.max(...trackIntervals.map((interval) => interval.end_s))
    : null;
  const times = state.velocity.elapsed_s;
  state.view = [times[0], state.scopeEnd === null ? times[times.length - 1] : Math.min(state.scopeEnd, times[times.length - 1])];
  el("reset-zoom").disabled = true;
  renderScopedData(); renderChart();
});
el("reset-zoom").addEventListener("click", () => {
  const times = state.velocity.elapsed_s;
  state.view = [times[0], state.scopeEnd === null ? times[times.length - 1] : Math.min(state.scopeEnd, times[times.length - 1])];
  el("reset-zoom").disabled = true; renderChart();
});
new ResizeObserver(() => { if (state.velocity) renderChart(); }).observe(el("chart"));
loadDashboard();
