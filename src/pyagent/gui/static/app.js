"use strict";

/* pyagent GUI —— 本地服务的原生 JS 客户端。
 * 连接 /api/stream（SSE），分发事件，渲染 Codex 风格聊天界面。 */

const state = {
  sessionId: null,
  running: false,
  currentAssistant: null, // 正在流式写入的助手气泡
  toolCardQueue: [],      // 等待结果的工具卡片队列（FIFO）
  permissionReq: null,
  diffReq: null,
};

const $ = (sel) => document.querySelector(sel);
const messagesEl = $("#messages");
const inputEl = $("#input");
const statusEl = $("#status");

/* ---------- 辅助 ---------- */
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function autoscroll() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function post(url, data) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data || {}),
  });
  return r.json();
}

function setStatus(text) {
  statusEl.textContent = text || "";
}

function setRunning(on) {
  state.running = on;
  inputEl.disabled = on;
  $("#send").disabled = on;
  setStatus(on ? "运行中…" : "");
}

/* ---------- 渲染 ---------- */
function appendMessage(role, content) {
  const wrap = el("div", `msg ${role}`);
  const bubble = el("div", "bubble");
  bubble.textContent = content || "";
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  return wrap;
}

function makeToolCard(name, preview) {
  const card = el("div", "tool-card");
  const head = el("div", "tool-head");
  head.appendChild(el("span", "tool-name", name));
  const pv = el("span", "tool-preview", preview.length > 90 ? preview.slice(0, 90) + "…" : preview);
  pv.title = preview;
  head.appendChild(pv);
  card.appendChild(head);
  const body = el("div", "tool-body hidden");
  card.appendChild(body);
  card.addEventListener("click", () => body.classList.toggle("hidden"));
  return card;
}

function setToolStatus(card, ok, content) {
  card.classList.remove("running");
  card.classList.add(ok ? "ok" : "fail");
  const nameNode = card.querySelector(".tool-name");
  nameNode.textContent = `${ok ? "✓" : "✗"} ${nameNode.textContent}`;
  const body = card.querySelector(".tool-body");
  if (content) {
    body.textContent = content.length > 1000 ? content.slice(0, 1000) + "\n…(已截断)" : content;
    body.classList.remove("hidden");
  }
}

function ensureAssistant() {
  if (!state.currentAssistant) {
    state.currentAssistant = appendMessage("assistant", "");
    state.toolCardQueue = [];
  }
  return state.currentAssistant.querySelector(".bubble");
}

function renderHistory(messages) {
  messagesEl.innerHTML = "";
  state.currentAssistant = null;
  state.toolCardQueue = [];
  let lastToolCard = null;
  for (const m of messages || []) {
    if (m.role === "system") continue;
    if (m.role === "user") {
      appendMessage("user", m.content);
    } else if (m.role === "assistant") {
      if (m.content) appendMessage("assistant", m.content);
      if (m.tool_calls && m.tool_calls.length) {
        for (const tc of m.tool_calls) {
          const fn = tc.function || {};
          const card = makeToolCard(fn.name || tc.name || "tool", fn.arguments || "");
          card.classList.add("ok");
          messagesEl.appendChild(card);
          lastToolCard = card;
        }
      }
    } else if (m.role === "tool") {
      if (lastToolCard) setToolStatus(lastToolCard, !m.content.startsWith("Error"), m.content);
    }
  }
  autoscroll();
}

function renderDiff(pre, diffText) {
  pre.innerHTML = "";
  for (const line of (diffText || "").split("\n")) {
    const d = el("div", "diff-line");
    if (line.startsWith("+")) d.classList.add("add");
    else if (line.startsWith("-")) d.classList.add("del");
    else if (line.startsWith("@@")) d.classList.add("hunk");
    d.textContent = line;
    pre.appendChild(d);
  }
}

/* ---------- 事件分发 ---------- */
function handle(msg) {
  switch (msg.type) {
    case "snapshot":
      state.sessionId = msg.session_id;
      renderHistory(msg.messages || []);
      break;
    case "assistant_delta":
      ensureAssistant().textContent += msg.text;
      autoscroll();
      break;
    case "tool_start": {
      const card = makeToolCard(msg.name, msg.preview);
      card.classList.add("running");
      (state.currentAssistant || messagesEl).appendChild(card);
      state.toolCardQueue.push(card);
      autoscroll();
      break;
    }
    case "tool_result": {
      const card = state.toolCardQueue.shift();
      if (card) setToolStatus(card, msg.ok, msg.content);
      autoscroll();
      break;
    }
    case "final":
      if (state.currentAssistant) {
        const bubble = state.currentAssistant.querySelector(".bubble");
        bubble.textContent = msg.content || bubble.textContent;
        autoscroll();
      }
      break;
    case "permission":
      showPermission(msg);
      break;
    case "diff":
      showDiff(msg);
      break;
    case "error":
      appendMessage("error", msg.message || "发生错误");
      autoscroll();
      break;
    case "run_end":
      setRunning(false);
      state.currentAssistant = null;
      state.toolCardQueue = [];
      loadSessions();
      break;
    default:
      break;
  }
}

/* ---------- SSE ---------- */
function connect() {
  const es = new EventSource("/api/stream");
  es.onmessage = (e) => {
    let msg;
    try {
      msg = JSON.parse(e.data);
    } catch {
      return;
    }
    handle(msg);
  };
  // EventSource 出错时会自动重连。
}

/* ---------- 权限 / diff ---------- */
function showPermission(msg) {
  state.permissionReq = msg;
  $("#permission-text").textContent = `${msg.action} on: ${msg.target}`;
  $("#permission-modal").classList.remove("hidden");
}

$("#permission-modal").querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const req = state.permissionReq;
    try {
      if (req) {
        await post("/api/permission", {
          id: req.id,
          decision: btn.dataset.decision,
          remember: btn.dataset.remember === "true",
        });
      }
    } catch (err) {
      appendMessage("error", "权限确认发送失败：" + err);
    } finally {
      state.permissionReq = null;
      $("#permission-modal").classList.add("hidden");
    }
  });
});

function showDiff(msg) {
  state.diffReq = msg;
  $("#diff-path").textContent = msg.path;
  renderDiff($("#diff-body"), msg.diff);
  $("#diff-modal").classList.remove("hidden");
}

$("#diff-apply").addEventListener("click", async () => {
  const req = state.diffReq;
  try {
    if (req) await post("/api/diff", { id: req.id, apply: true });
  } catch (err) {
    appendMessage("error", "diff 确认发送失败：" + err);
  } finally {
    state.diffReq = null;
    $("#diff-modal").classList.add("hidden");
  }
});

$("#diff-cancel").addEventListener("click", async () => {
  const req = state.diffReq;
  try {
    if (req) await post("/api/diff", { id: req.id, apply: false });
  } catch (err) {
    appendMessage("error", "diff 确认发送失败：" + err);
  } finally {
    state.diffReq = null;
    $("#diff-modal").classList.add("hidden");
  }
});

/* ---------- 输入 / 聊天 ---------- */
async function sendPrompt() {
  const text = inputEl.value.trim();
  if (!text || state.running) return;
  inputEl.value = "";
  appendMessage("user", text);
  setRunning(true);
  const res = await post("/api/chat", { prompt: text });
  if (!res.ok) {
    setRunning(false);
    appendMessage("error", res.error || "无法启动任务");
  }
}

$("#input-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sendPrompt();
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendPrompt();
  }
});

/* ---------- 会话 ---------- */
async function loadSessions() {
  try {
    const r = await fetch("/api/sessions");
    const data = await r.json();
    const list = $("#session-list");
    list.innerHTML = "";
    for (const s of data.sessions || []) {
      const item = el("div", "session-item");
      if (s.session_id === state.sessionId) item.classList.add("active");
      item.appendChild(el("div", "session-title", s.title || s.session_id));
      item.appendChild(el("div", "session-meta", `${s.message_count} 条消息 · ${s.updated_at}`));
      item.addEventListener("click", () => resumeSession(s.session_id));
      list.appendChild(item);
    }
  } catch {
    /* 服务还没就绪，忽略 */
  }
}

async function resumeSession(sid) {
  if (state.running) return;
  const res = await post("/api/resume", { session_id: sid });
  if (res.ok) {
    state.sessionId = res.session_id;
    renderHistory(res.messages);
    loadSessions();
  } else {
    appendMessage("error", res.error || "恢复会话失败");
  }
}

$("#new-chat").addEventListener("click", async () => {
  if (state.running) return;
  const res = await post("/api/new", {});
  if (res.ok) {
    state.sessionId = res.session_id;
    renderHistory([]);
    loadSessions();
  }
});

async function loadHealth() {
  try {
    const r = await fetch("/api/health");
    const h = await r.json();
    const info = $("#config-info");
    info.innerHTML = "";
    info.appendChild(el("div", "cfg", `模型 ${h.model}`));
    info.appendChild(el("div", "cfg", `目录 ${h.cwd}`));
  } catch {
    /* 忽略 */
  }
}

/* ---------- 初始化 ---------- */
window.addEventListener("load", () => {
  connect();
  loadSessions();
  loadHealth();
  inputEl.focus();
});
