"use strict";

const POLL_MS = 1000;
const DRAW_MS = 33;
const CHART_WINDOW_MS = 60000;
const KEEP_MS = 120000;
const $ = id => document.getElementById(id);
const frames = [];
const series = new Map();
const tableRows = new Map();
let accessToken = sessionStorage.getItem("tucamRemoteToken") || "";
let cursor = 0;
let streamEpoch = "";
let clockOffsetMs = 0;
let clockReady = false;
let polling = false;
let latestStatus = {};
let lastDrawAt = 0;
let fpsStartedAt = performance.now();
let fpsFrames = 0;

$("token").value = accessToken;

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {}, {Authorization: `Bearer ${accessToken}`});
  const response = await fetch(path, Object.assign({}, options, {headers, cache: "no-store"}));
  if (response.status === 401 || response.status === 403) throw new Error("访问密钥错误或当前电脑未被允许");
  let payload = {};
  try { payload = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function setLinked(ok, text) {
  $("dot").className = `dot ${ok ? "ok" : "bad"}`;
  $("linkState").textContent = text;
}

function fmt(value, suffix = "") {
  return value === undefined || value === null || value === "--" ? "--" : `${value}${suffix}`;
}

function renderLiveStatus(data) {
  latestStatus = data || {};
  $("camera").textContent = data.connected ? "已连接" : "未连接";
  $("capture").textContent = data.batch_running ? "批量测试" : data.capturing ? "连续采集" : "已停止";
  $("message").textContent = data.status || "--";
  $("start").disabled = !data.connected || data.capturing || data.batch_running;
  $("stop").disabled = !data.capturing && !data.batch_running;
}

function clearStream() {
  frames.length = 0;
  series.clear();
  cursor = 0;
  tableRows.clear();
  $("rows").replaceChildren();
  updateSeriesOptions();
}

function frameKey(item) {
  return `${item.probe_id || item.probe || ""}\u0000${item.gas || ""}`;
}

function addFrame(frame) {
  if (!frame || !Number.isFinite(Number(frame.timestamp_ms))) return;
  frame.timestamp_ms = Number(frame.timestamp_ms);
  frames.push(frame);
  if (frame.kind !== "measurement") return;
  for (const item of frame.concentrations || []) {
    const key = frameKey(item);
    if (!series.has(key)) series.set(key, {label: `${item.probe || item.probe_id || "--"} · ${item.gas || "--"}`, points: []});
    series.get(key).points.push({t: frame.timestamp_ms, y: Number(item.concentration_percent), item});
  }
}

function pruneFrames() {
  const newest = frames.length ? frames[frames.length - 1].timestamp_ms : 0;
  const cutoff = newest - KEEP_MS;
  while (frames.length && frames[0].timestamp_ms < cutoff) frames.shift();
  for (const [key, value] of series) {
    while (value.points.length && value.points[0].t < cutoff) value.points.shift();
    if (!value.points.length) series.delete(key);
  }
}

function updateSeriesOptions() {
  const selected = $("series").value;
  const keys = Array.from(series.keys());
  $("series").replaceChildren(...keys.map(key => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = series.get(key).label;
    return option;
  }));
  if (keys.includes(selected)) $("series").value = selected;
}

async function pollUpdates() {
  if (polling || !accessToken) return;
  polling = true;
  const requestStarted = performance.now();
  try {
    let more = true;
    let passes = 0;
    while (more && passes < 8) {
      const sentWallMs = Date.now();
      const data = await api(`/api/updates?after=${cursor}&limit=500`);
      const receivedWallMs = Date.now();
      const sampleOffset = Number(data.server_time_ms) - (sentWallMs + receivedWallMs) / 2;
      clockOffsetMs = clockReady ? clockOffsetMs * 0.85 + sampleOffset * 0.15 : sampleOffset;
      clockReady = true;
      if (streamEpoch && data.stream_epoch !== streamEpoch) clearStream();
      streamEpoch = data.stream_epoch || streamEpoch;
      if (data.reset_required) clearStream();
      for (const frame of data.measurements || []) {
        addFrame(frame);
        cursor = Math.max(cursor, Number(frame.id) || 0);
      }
      renderLiveStatus(data.status || {});
      more = Boolean(data.has_more);
      passes += 1;
    }
    pruneFrames();
    updateSeriesOptions();
    $("buffer").textContent = String(frames.filter(frame => frame.kind === "measurement").length);
    $("latency").textContent = `${Math.round(performance.now() - requestStarted)} ms`;
    $("login").classList.add("hidden");
    setLinked(true, "局域网已连接");
  } catch (error) {
    setLinked(false, "连接中断");
    if (String(error.message).includes("密钥") || String(error.message).includes("允许")) {
      $("login").classList.remove("hidden");
      $("loginError").textContent = error.message;
    }
  } finally {
    polling = false;
  }
}

function playheadTime() {
  return Date.now() + clockOffsetMs - Number($("delay").value) * 1000;
}

function measurementPair(at) {
  let before = null;
  let after = null;
  let gapAfterBefore = false;
  for (const frame of frames) {
    if (frame.timestamp_ms <= at) {
      if (frame.kind === "measurement") { before = frame; gapAfterBefore = false; }
      else if (before) gapAfterBefore = true;
    } else {
      if (frame.kind === "gap") gapAfterBefore = true;
      if (frame.kind === "measurement") { after = frame; break; }
    }
  }
  return {before, after, gap: gapAfterBefore};
}

function interpolatedItems(at) {
  const {before, after, gap} = measurementPair(at);
  if (!before) return {items: [], time: null};
  const beforeMap = new Map((before.concentrations || []).map(item => [frameKey(item), item]));
  const afterMap = new Map((after?.concentrations || []).map(item => [frameKey(item), item]));
  const span = after ? after.timestamp_ms - before.timestamp_ms : 0;
  const rawRatio = span > 0 ? (at - before.timestamp_ms) / span : 0;
  const ratio = gap ? 0 : Math.max(0, Math.min(1, rawRatio));
  const eased = ratio * ratio * (3 - 2 * ratio);
  const items = Array.from(beforeMap, ([key, item]) => {
    const next = afterMap.get(key);
    const start = Number(item.concentration_percent);
    const end = next ? Number(next.concentration_percent) : start;
    return Object.assign({}, item, {concentration_percent: start + (end - start) * eased});
  });
  return {items, time: new Date(at)};
}

function updateTable(items, shownTime) {
  const active = new Set();
  for (const item of items) {
    const key = frameKey(item);
    active.add(key);
    let cells = tableRows.get(key);
    if (!cells) {
      const row = $("rows").insertRow();
      cells = [row.insertCell(), row.insertCell(), row.insertCell(), row.insertCell()];
      cells[2].className = "value";
      tableRows.set(key, cells);
    }
    const values = [item.probe || item.probe_id || "--", item.gas || "--", Number(item.concentration_percent).toFixed(3), item.detected ? "已检出" : "未检出"];
    cells.forEach((cell, index) => { if (cell.textContent !== values[index]) cell.textContent = values[index]; });
  }
  for (const [key, cells] of tableRows) {
    if (!active.has(key)) { cells[0].parentElement.remove(); tableRows.delete(key); }
  }
  $("empty").style.display = items.length ? "none" : "block";
  $("measurementTime").textContent = shownTime ? shownTime.toLocaleString("zh-CN", {hour12: false}) : "--";
}

function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * scale));
  const height = Math.max(1, Math.round(rect.height * scale));
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  return {rect, scale};
}

function crossesGap(start, end) {
  return frames.some(frame => frame.kind === "gap" && frame.timestamp_ms > start && frame.timestamp_ms <= end);
}

function drawChart(at, currentItems) {
  const canvas = $("chart");
  const {rect, scale} = resizeCanvas(canvas);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  const width = rect.width, height = rect.height;
  ctx.clearRect(0, 0, width, height);
  const selected = series.get($("series").value);
  const left = 52, right = 14, top = 14, bottom = 32;
  ctx.strokeStyle = "#e2e6ea"; ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i += 1) { const y = top + (height - top - bottom) * i / 5; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(width - right, y); ctx.stroke(); }
  ctx.fillStyle = "#66727e"; ctx.font = "12px Segoe UI";
  if (!selected) { ctx.fillText("等待浓度数据", left + 12, top + 24); return; }
  const from = at - CHART_WINDOW_MS;
  const points = selected.points.filter(point => point.t >= from && point.t <= at).map(point => ({t: point.t, y: point.y}));
  const current = currentItems.find(item => frameKey(item) === $("series").value);
  if (current && (!points.length || points[points.length - 1].t < at)) points.push({t: at, y: Number(current.concentration_percent)});
  if (!points.length) { ctx.fillText("正在建立数据缓冲", left + 12, top + 24); return; }
  const values = points.map(point => point.y);
  let yMin = Math.max(0, Math.min(...values)); let yMax = Math.max(...values);
  const pad = Math.max(1, (yMax - yMin) * 0.12); yMin = Math.max(0, yMin - pad); yMax += pad;
  if (Math.max(...values) >= 99) yMax = Math.max(100, yMax); if (yMax <= yMin) yMax = yMin + 2;
  ctx.fillText(yMax.toFixed(1), 4, top + 5); ctx.fillText(yMin.toFixed(1), 4, height - bottom + 4);
  const xAt = time => left + (width - left - right) * (time - from) / CHART_WINDOW_MS;
  const yAt = value => top + (height - top - bottom) * (1 - (value - yMin) / (yMax - yMin));
  ctx.strokeStyle = "#1769aa"; ctx.lineWidth = 2; ctx.beginPath();
  points.forEach((point, index) => {
    const broken = index > 0 && crossesGap(points[index - 1].t, point.t);
    if (!index || broken) ctx.moveTo(xAt(point.t), yAt(point.y)); else ctx.lineTo(xAt(point.t), yAt(point.y));
  });
  ctx.stroke();
  const last = points[points.length - 1]; ctx.fillStyle = "#1769aa"; ctx.beginPath(); ctx.arc(xAt(last.t), yAt(last.y), 3.5, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#66727e"; ctx.fillText(new Date(from).toLocaleTimeString("zh-CN", {hour12:false}), left, height - 8); ctx.textAlign = "right"; ctx.fillText(new Date(at).toLocaleTimeString("zh-CN", {hour12:false}), width - right, height - 8); ctx.textAlign = "left";
}

function animate(now) {
  requestAnimationFrame(animate);
  if (document.hidden || now - lastDrawAt < DRAW_MS) return;
  lastDrawAt = now;
  const at = playheadTime();
  const shown = interpolatedItems(at);
  updateTable(shown.items, shown.time);
  drawChart(at, shown.items);
  const newest = frames.length ? frames[frames.length - 1].timestamp_ms : 0;
  $("dataAge").textContent = newest ? `${Math.max(0, (Date.now() + clockOffsetMs - newest) / 1000).toFixed(1)} 秒` : "--";
  fpsFrames += 1;
  if (now - fpsStartedAt >= 1000) { $("remoteFps").textContent = `${(fpsFrames * 1000 / (now - fpsStartedAt)).toFixed(1)} FPS`; fpsFrames = 0; fpsStartedAt = now; }
}

async function waitForCommand(commandId) {
  const deadline = Date.now() + 6000;
  while (Date.now() < deadline) {
    const result = await api(`/api/commands/${commandId}`);
    if (result.state === "completed") return result;
    await new Promise(resolve => setTimeout(resolve, 120));
  }
  throw new Error("现场程序未在 6 秒内确认命令");
}

async function command(action) {
  $("start").disabled = true; $("stop").disabled = true;
  try {
    const response = await api(`/api/commands/${action}`, {method: "POST"});
    $("message").textContent = "命令已发送，等待现场程序确认";
    const result = await waitForCommand(response.command.command_id);
    $("message").textContent = result.message || (result.ok ? "命令已执行" : "命令执行失败");
    await pollUpdates();
  } catch (error) { $("message").textContent = `命令失败：${error.message}`; }
  finally { renderLiveStatus(latestStatus); }
}

$("connect").onclick = async () => { accessToken = $("token").value.trim(); sessionStorage.setItem("tucamRemoteToken", accessToken); $("loginError").textContent = ""; await pollUpdates(); };
$("start").onclick = () => command("start"); $("stop").onclick = () => command("stop");
$("emergency").onclick = () => { if (confirm("确认立即停止现场采集？")) command("emergency-stop"); };
$("delay").onchange = () => { fpsFrames = 0; fpsStartedAt = performance.now(); };
document.addEventListener("visibilitychange", () => { if (!document.hidden) { fpsFrames = 0; fpsStartedAt = performance.now(); pollUpdates(); } });
setInterval(pollUpdates, POLL_MS); requestAnimationFrame(animate); pollUpdates();
