"use strict";

/* 地平线测点默认值：方位角北 0° 顺时针，遮挡仰角单位为度 */
const DEFAULT_POINTS = [
  { azimuth: 0, elevation: 10 },
  { azimuth: 90, elevation: 20 },
  { azimuth: 180, elevation: 8 },
  { azimuth: 270, elevation: 30 },
];
const MIN_POINTS = 2;
const MAX_POINTS = 12;

const form = document.getElementById("calc-form");
const pointsBody = document.getElementById("points-body");
const addBtn = document.getElementById("add-point");

/* ---------- 测点增删 ---------- */

function addPointRow(az = "", el = "") {
  const idx = pointsBody.rows.length;
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td class="idx">${idx + 1}</td>
    <td>
      <input type="number" step="0.1" min="0" max="359.999"
             name="azimuth" value="${az}" placeholder="0 ≤ 方位角 < 360"
             aria-label="方位角" />
      <small class="err" data-error="azimuth"></small>
    </td>
    <td>
      <input type="number" step="0.1" min="0" max="80"
             name="elevation" value="${el}" placeholder="0～80"
             aria-label="遮挡仰角" />
      <small class="err" data-error="elevation"></small>
    </td>
    <td class="op">
      <button type="button" class="btn ghost remove-point">删除</button>
    </td>`;
  pointsBody.appendChild(tr);
  updateRowState();
}

function updateRowState() {
  const n = pointsBody.rows.length;
  addBtn.disabled = n >= MAX_POINTS;
  for (const row of pointsBody.rows) {
    row.querySelector(".idx").textContent = row.rowIndex;
    row.querySelector(".remove-point").disabled = n <= MIN_POINTS;
  }
}

addBtn.addEventListener("click", () => addPointRow());
pointsBody.addEventListener("click", (e) => {
  if (e.target.classList.contains("remove-point")) {
    e.target.closest("tr").remove();
    updateRowState();
  }
});

/* ---------- 错误展示 ---------- */

function clearErrors() {
  for (const el of form.querySelectorAll(".err")) el.textContent = "";
  for (const el of form.querySelectorAll(".invalid")) el.classList.remove("invalid");
}

function fieldError(selector, message) {
  const errEl = form.querySelector(`.err[data-error="${selector}"]`);
  if (errEl) {
    errEl.textContent = message;
    const input = errEl.closest("label, td")?.querySelector("input, select");
    if (input) input.classList.add("invalid");
  }
}

function showServerErrors(errors) {
  for (const [key, message] of Object.entries(errors)) {
    if (key.startsWith("points.")) {
      const rest = key.slice("points.".length);
      const dot = rest.indexOf(".");
      if (dot >= 0) {
        const rowIdx = Number(rest.slice(0, dot));
        const name = rest.slice(dot + 1);
        const row = pointsBody.rows[rowIdx];
        if (row) {
          const errEl = row.querySelector(`.err[data-error="${name}"]`);
          if (errEl) {
            errEl.textContent = message;
            row.querySelector(`input[name="${name}"]`)?.classList.add("invalid");
          }
          return;
        }
      }
      fieldError("points", message);
    } else {
      fieldError(key, message);
    }
  }
}

/* ---------- 表单收集与客户端校验 ---------- */

function collectPayload() {
  const points = [];
  const seen = new Set();
  let pointsValid = true;

  for (let i = 0; i < pointsBody.rows.length; i++) {
    const row = pointsBody.rows[i];
    const azRaw = row.querySelector('input[name="azimuth"]').value.trim();
    const elRaw = row.querySelector('input[name="elevation"]').value.trim();
    const azErr = row.querySelector('.err[data-error="azimuth"]');
    const elErr = row.querySelector('.err[data-error="elevation"]');
    azErr.textContent = "";
    elErr.textContent = "";

    const az = Number(azRaw);
    const elev = Number(elRaw);
    let rowOk = true;
    if (azRaw === "" || !Number.isFinite(az) || az < 0 || az >= 360) {
      azErr.textContent = "方位角须为 [0, 360) 内的数字";
      row.querySelector('input[name="azimuth"]').classList.add("invalid");
      rowOk = false;
    } else if (seen.has(az)) {
      azErr.textContent = `方位角 ${az}° 重复`;
      row.querySelector('input[name="azimuth"]').classList.add("invalid");
      rowOk = false;
    }
    if (elRaw === "" || !Number.isFinite(elev) || elev < 0 || elev > 80) {
      elErr.textContent = "遮挡仰角须为 0～80 的数字";
      row.querySelector('input[name="elevation"]').classList.add("invalid");
      rowOk = false;
    }
    if (rowOk) {
      seen.add(az);
      points.push({ azimuth: az, elevation: elev });
    } else {
      pointsValid = false;
    }
  }

  const payload = {
    date: form.elements["date"].value,
    latitude: Number(form.elements["latitude"].value),
    longitude: Number(form.elements["longitude"].value),
    timezone: form.elements["timezone"].value,
    points,
  };
  return { payload, pointsValid };
}

/* ---------- 结果渲染 ---------- */

const results = document.getElementById("results");
const summary = document.getElementById("summary");
const dstBanner = document.getElementById("dst-banner");
const timeline = document.getElementById("timeline");
const intervalList = document.getElementById("interval-list");

function fmtHours(totalMinutes) {
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return m ? `${h} 小时 ${m} 分` : `${h} 小时`;
}

function renderSummary(data) {
  const dayHours = fmtHours(data.total_local_minutes);
  const cls = data.sunlit_minutes > 0 ? "num" : "num zero";
  summary.innerHTML = `
    <div><span class="${cls}">${data.sunlit_minutes}</span> 分钟直晒
      （共 ${data.intervals.length} 段）</div>
    <div>当地日长：<strong>${dayHours}</strong>
      <span class="hint" style="display:inline">
      （${data.date} 00:00 至次日 00:00，按 UTC 整分钟遍历）</span></div>`;
}

function renderDstBanner(data) {
  if (!data.transitions.length) {
    dstBanner.classList.add("hidden");
    dstBanner.textContent = "";
    return;
  }
  const parts = data.transitions.map((t) => {
    const action = t.kind === "forward" ? "时钟拨快" : "时钟回拨";
    return `${t.local.date} ${t.local.time}（${action} ${t.delta_minutes} 分钟，
      UTC${t.old_offset} → UTC${t.new_offset}）`;
  });
  dstBanner.innerHTML =
    `⚠ 本日发生夏令时切换：${parts.join("；")}。` +
    `当天本地时长按实际 ${fmtHours(data.total_local_minutes)} 处理，` +
    `回拨产生的重复本地时刻分别计算、不会合并。`;
  dstBanner.classList.remove("hidden");
}

function renderTimeline(data) {
  timeline.innerHTML = "";
  const total = data.total_local_minutes;

  for (const iv of data.intervals) {
    const bar = document.createElement("div");
    bar.className = "tl-bar";
    bar.style.left = `${(iv.start_minute / total) * 100}%`;
    bar.style.width = `${((iv.end_minute - iv.start_minute) / total) * 100}%`;
    bar.title = `${iv.label}（${iv.minutes} 分钟）`;
    timeline.appendChild(bar);
  }

  for (const t of data.transitions) {
    const line = document.createElement("div");
    line.className = "tl-dst";
    line.style.left = `${(t.at_minute / total) * 100}%`;
    line.title = `夏令时切换 UTC${t.old_offset} → UTC${t.new_offset}`;
    line.innerHTML =
      `<span class="dst-tag">${t.kind === "forward" ? "拨快" : "回拨"} ${t.delta_minutes}′</span>
       <span class="dst-sub">${t.local.time}</span>`;
    timeline.appendChild(line);
  }

  const ticks = document.createElement("div");
  ticks.className = "tl-ticks";
  data.ticks.forEach((tick, i) => {
    const lab = document.createElement("span");
    lab.className = "tl-tick";
    lab.style.left = `${(tick.minute / total) * 100}%`;
    const showOffset = i === 0 || i === data.ticks.length - 1;
    lab.textContent = showOffset
      ? `${tick.local.time} ${tick.local.offset}`
      : tick.local.time;
    ticks.appendChild(lab);
  });
  timeline.appendChild(ticks);
}

function renderIntervals(data) {
  intervalList.innerHTML = "";
  if (!data.intervals.length) {
    const li = document.createElement("li");
    li.className = "empty-note";
    li.textContent = "无直晒时段（0 分钟），列表为空。";
    intervalList.appendChild(li);
    return;
  }
  data.intervals.forEach((iv, i) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<span><strong>${i + 1}.</strong> ${iv.label}
        <span class="hint">（半开：含起始分钟、不含结束分钟）</span></span>
       <span class="mins">${iv.minutes} 分钟</span>`;
    intervalList.appendChild(li);
  });
}

/* ---------- 极坐标剖面图 ---------- */

const SVG_NS = "http://www.w3.org/2000/svg";
const CX = 180, CY = 180, R_MAX = 150;

function polar(azimuthDeg, radius) {
  // 北朝上（-y），顺时针方位角
  const a = (azimuthDeg * Math.PI) / 180;
  return [CX + radius * Math.sin(a), CY - radius * Math.cos(a)];
}

function svgEl(name, attrs) {
  const el = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  return el;
}

function renderProfileChart(data) {
  const svg = document.getElementById("profile-chart");
  svg.innerHTML = "";

  // 背景与高度环（仰角 0/20/40/60/80；仰角越大半径越小）
  svg.appendChild(svgEl("circle", { cx: CX, cy: CY, r: R_MAX, fill: "#f8fafc", stroke: "#c7d0db" }));
  for (const e of [20, 40, 60, 80]) {
    const r = R_MAX * (1 - e / 90);
    svg.appendChild(svgEl("circle", { cx: CX, cy: CY, r, fill: "none", stroke: "#e3e9f0" }));
    const [tx, ty] = polar(0, r);
    const t = svgEl("text", { x: CX + 4, y: ty + 3, "font-size": 9, fill: "#8895a3" });
    t.textContent = `${e}°`;
    svg.appendChild(t);
  }
  // 方位轴
  for (const a of [0, 90, 180, 270]) {
    const [x, y] = polar(a, R_MAX);
    svg.appendChild(svgEl("line", { x1: CX, y1: CY, x2: x, y2: y, stroke: "#e3e9f0" }));
    const [lx, ly] = polar(a, R_MAX + 14);
    const t = svgEl("text", { x: lx, y: ly + 3, "font-size": 11, fill: "#647281",
      "text-anchor": "middle" });
    t.textContent = { 0: "北 0°", 90: "东 90°", 180: "南 180°", 270: "西 270°" }[a];
    svg.appendChild(t);
  }

  // 遮挡区域（剖面线到外缘之间）
  const hz = data.horizon;
  if (hz.length) {
    const closed = [...hz, { ...hz[0], azimuth: hz[0].azimuth + 360 }];
    let d = "";
    closed.forEach((p, i) => {
      const r = R_MAX * (1 - Math.min(p.elevation, 80) / 90);
      const [x, y] = polar(p.azimuth, r);
      d += `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)} `;
    });
    // 沿外缘闭合
    for (let i = closed.length - 1; i >= 0; i--) {
      const p = closed[i];
      const [x, y] = polar(p.azimuth, R_MAX);
      d += `L${x.toFixed(1)},${y.toFixed(1)} `;
    }
    svg.appendChild(svgEl("path", { d: d + "Z", fill: "rgba(120,134,156,0.35)", stroke: "none" }));

    // 剖面折线
    let hd = "";
    closed.forEach((p, i) => {
      const r = R_MAX * (1 - Math.min(p.elevation, 80) / 90);
      const [x, y] = polar(p.azimuth, r);
      hd += `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)} `;
    });
    svg.appendChild(svgEl("path", { d: hd, fill: "none", stroke: "#54637a", "stroke-width": 1.8 }));
    hz.forEach((p) => {
      const r = R_MAX * (1 - Math.min(p.elevation, 80) / 90);
      const [x, y] = polar(p.azimuth, r);
      svg.appendChild(svgEl("circle", { cx: x, cy: y, r: 2.6, fill: "#54637a" }));
    });
  }

  // 太阳样本：直晒为橙点，被遮挡/夜间为灰点
  for (const s of data.samples) {
    if (s.elevation <= 0) continue;
    const r = R_MAX * (1 - Math.min(s.elevation, 90) / 90);
    const [x, y] = polar(s.azimuth, r);
    svg.appendChild(svgEl("circle", {
      cx: x, cy: y, r: 2.4,
      fill: s.sunlit ? "#f5a623" : "rgba(120,134,156,0.65)",
    }));
  }
}

/* ---------- 提交 ---------- */

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearErrors();
  const { payload, pointsValid } = collectPayload();

  let clientOk = pointsValid;
  if (!payload.date) {
    fieldError("date", "请选择日期");
    clientOk = false;
  }
  if (!Number.isFinite(payload.latitude) || payload.latitude < -66 || payload.latitude > 66) {
    fieldError("latitude", "纬度须为 -66～66 的数字");
    clientOk = false;
  }
  if (!Number.isFinite(payload.longitude) || payload.longitude < -180 || payload.longitude > 180) {
    fieldError("longitude", "经度须为 -180～180 的数字");
    clientOk = false;
  }
  if (!clientOk) return;
  const btn = document.getElementById("submit-btn");
  btn.disabled = true;
  btn.textContent = "计算中…";
  try {
    const resp = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      showServerErrors(data.errors || { _: "计算失败，请检查输入" });
      results.classList.add("hidden");
      return;
    }
    renderSummary(data);
    renderDstBanner(data);
    renderTimeline(data);
    renderIntervals(data);
    renderProfileChart(data);
    results.classList.remove("hidden");
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    fieldError("_", `请求失败：${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "计算直晒窗口";
  }
});

/* ---------- 初始化 ---------- */

document.getElementById("date").value = new Date().toISOString().slice(0, 10);
DEFAULT_POINTS.forEach((p) => addPointRow(p.azimuth, p.elevation));
