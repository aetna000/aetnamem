APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>aetnamem</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg:#f2f4f8; --panel:#ffffff; --panel-2:#f7f8fb;
      --ink:#1c2430; --muted:#68748a; --line:#e3e7ee; --line-strong:#d3d9e3;
      --accent:#4462e0; --accent-ink:#ffffff; --accent-soft:rgba(68,98,224,.09);
      --ok:#1e7a4d; --ok-soft:rgba(30,122,77,.12);
      --warn:#9a6200; --warn-soft:rgba(154,98,0,.13);
      --bad:#c0392b; --bad-soft:rgba(192,57,43,.11);
      --shadow:0 1px 2px rgba(16,24,40,.05), 0 4px 16px rgba(16,24,40,.06);
      --radius:14px;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg:#0e1116; --panel:#161b23; --panel-2:#1b212b;
        --ink:#e9edf5; --muted:#93a0b4; --line:#242c38; --line-strong:#303a49;
        --accent:#6c86f5; --accent-soft:rgba(108,134,245,.14);
        --ok:#3ecf8e; --ok-soft:rgba(62,207,142,.13);
        --warn:#e2a33c; --warn-soft:rgba(226,163,60,.13);
        --bad:#f06a5d; --bad-soft:rgba(240,106,93,.13);
        --shadow:0 1px 2px rgba(0,0,0,.4), 0 6px 20px rgba(0,0,0,.35);
      }
    }
    * { box-sizing:border-box; }
    html, body { height:100%; }
    body {
      margin:0; background:var(--bg); color:var(--ink);
      font:14px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
      -webkit-font-smoothing:antialiased;
    }
    button { font:inherit; cursor:pointer; }
    input, textarea, select { font:inherit; color:var(--ink); }

    /* ---------- header ---------- */
    header {
      position:sticky; top:0; z-index:20;
      display:flex; align-items:center; gap:14px;
      padding:12px 22px; background:var(--panel);
      border-bottom:1px solid var(--line);
    }
    .brand { display:flex; align-items:center; gap:10px; font-weight:700; font-size:16px; letter-spacing:-.01em; }
    .brand-mark {
      width:28px; height:28px; border-radius:8px; flex:none;
      background:linear-gradient(135deg, var(--accent), #8b5cf6);
      display:grid; place-items:center; color:#fff; font-size:14px; font-weight:800;
    }
    .brand small { display:block; font-weight:500; font-size:11.5px; color:var(--muted); letter-spacing:0; }
    .header-status { margin-left:auto; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .pill {
      display:inline-flex; align-items:center; gap:6px;
      font-size:12px; font-weight:600; color:var(--muted);
      border:1px solid var(--line); border-radius:999px; padding:4px 11px; background:var(--panel-2);
      white-space:nowrap;
    }
    .dot { width:7px; height:7px; border-radius:50%; background:var(--muted); flex:none; }
    .dot.ok { background:var(--ok); } .dot.warn { background:var(--warn); } .dot.bad { background:var(--bad); }
    .icon-btn {
      border:1px solid var(--line); background:var(--panel-2); color:var(--ink);
      border-radius:9px; padding:6px 12px; font-size:12.5px; font-weight:600;
    }
    .icon-btn:hover { border-color:var(--line-strong); background:var(--accent-soft); }

    /* ---------- layout ---------- */
    main {
      max-width:1240px; margin:0 auto; padding:20px 22px 32px;
      display:grid; grid-template-columns:minmax(0,7fr) minmax(340px,5fr); gap:18px;
      align-items:start;
    }
    @media (max-width: 980px) { main { grid-template-columns:1fr; } }
    .card {
      background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
      box-shadow:var(--shadow);
    }

    /* ---------- chat ---------- */
    .chat-card { display:flex; flex-direction:column; min-height:560px; max-height:calc(100vh - 130px); position:sticky; top:78px; }
    .card-head { display:flex; align-items:center; gap:10px; padding:14px 18px; border-bottom:1px solid var(--line); }
    .card-head h2 { margin:0; font-size:14px; font-weight:700; letter-spacing:-.01em; }
    .card-head .sub { color:var(--muted); font-size:12px; }
    #chat { flex:1; overflow-y:auto; padding:18px; display:flex; flex-direction:column; gap:12px; }
    .msg { max-width:86%; padding:10px 14px; border-radius:16px; white-space:pre-wrap; overflow-wrap:break-word; }
    .msg.user { align-self:flex-end; background:var(--accent); color:var(--accent-ink); border-bottom-right-radius:5px; }
    .msg.assistant { align-self:flex-start; background:var(--panel-2); border:1px solid var(--line); border-bottom-left-radius:5px; }
    .msg.notice { align-self:center; background:var(--warn-soft); color:var(--warn); font-size:12.5px; font-weight:600; border-radius:10px; padding:7px 12px; }
    .msg .tool {
      margin-top:8px; font-size:12px; color:var(--muted);
      border-top:1px dashed var(--line-strong); padding-top:7px;
    }
    .empty-chat { margin:auto; text-align:center; color:var(--muted); display:grid; gap:14px; justify-items:center; padding:20px; }
    .empty-chat .big { font-size:34px; }
    .chips { display:flex; gap:8px; flex-wrap:wrap; justify-content:center; }
    .chip {
      border:1px solid var(--line); background:var(--panel-2); color:var(--ink);
      border-radius:999px; padding:7px 13px; font-size:12.5px;
    }
    .chip:hover { border-color:var(--accent); color:var(--accent); background:var(--accent-soft); }
    .composer { display:flex; gap:10px; padding:14px 16px; border-top:1px solid var(--line); align-items:flex-end; }
    .composer textarea {
      flex:1; resize:none; min-height:44px; max-height:150px;
      border:1px solid var(--line-strong); border-radius:12px; padding:11px 13px;
      background:var(--panel-2); outline:none;
    }
    .composer textarea:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
    .send-btn {
      border:none; background:var(--accent); color:var(--accent-ink);
      border-radius:11px; padding:11px 18px; font-weight:700; flex:none;
    }
    .send-btn:disabled { opacity:.5; cursor:default; }
    .typing { align-self:flex-start; color:var(--muted); font-size:12.5px; padding:4px 6px; }

    /* ---------- right column ---------- */
    .side { display:grid; gap:18px; min-width:0; }
    .tabs { display:flex; gap:4px; padding:10px 12px 0; border-bottom:1px solid var(--line); }
    .tab {
      border:none; background:none; color:var(--muted); font-weight:600; font-size:13px;
      padding:8px 12px 10px; border-bottom:2px solid transparent; margin-bottom:-1px;
      display:inline-flex; align-items:center; gap:6px;
    }
    .tab.active { color:var(--accent); border-bottom-color:var(--accent); }
    .badge {
      background:var(--bad); color:#fff; font-size:10.5px; font-weight:800;
      border-radius:999px; min-width:17px; height:17px; padding:0 5px;
      display:none; align-items:center; justify-content:center;
    }
    .badge.show { display:inline-flex; }
    .panel { display:none; padding:14px; max-height:calc(100vh - 210px); overflow-y:auto; }
    .panel.active { display:grid; gap:10px; align-content:start; }
    .hint { color:var(--muted); font-size:12.5px; text-align:center; padding:22px 8px; }

    /* approvals */
    .approval { border:1px solid var(--line-strong); border-radius:12px; overflow:hidden; }
    .approval-head { display:flex; align-items:center; gap:8px; padding:10px 13px; background:var(--warn-soft); font-weight:700; font-size:13px; }
    .approval-body { padding:11px 13px; display:grid; gap:8px; font-size:12.5px; }
    .op { display:flex; align-items:center; gap:7px; flex-wrap:wrap; }
    .tag { border:1px solid var(--line); border-radius:6px; padding:2px 7px; font-size:11.5px; font-weight:600; color:var(--muted); background:var(--panel-2); }
    .tag.effect { color:var(--warn); border-color:transparent; background:var(--warn-soft); }
    .approval-meta { color:var(--muted); font-size:11.5px; }
    .approval-actions { display:flex; gap:8px; padding:0 13px 12px; }
    .btn { border-radius:9px; padding:8px 14px; font-weight:700; font-size:12.5px; border:1px solid transparent; }
    .btn.approve { background:var(--ok); color:#fff; flex:1; }
    .btn.deny { background:none; border-color:var(--line-strong); color:var(--bad); }
    details.raw summary { cursor:pointer; color:var(--muted); font-size:11.5px; }

    /* memory */
    .mem-toolbar { display:grid; grid-template-columns:1fr auto; gap:8px; }
    .mem-toolbar input, .mem-toolbar select {
      border:1px solid var(--line); border-radius:9px; padding:8px 11px; background:var(--panel-2); outline:none;
    }
    .mem-toolbar input:focus { border-color:var(--accent); }
    .mem-group-title { font-size:11.5px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); display:flex; align-items:center; gap:7px; margin-top:6px; }
    .mem-group-title .count { font-weight:700; background:var(--panel-2); border:1px solid var(--line); border-radius:999px; padding:1px 7px; }
    .mem-card { border:1px solid var(--line); border-radius:11px; padding:10px 12px; display:grid; gap:6px; background:var(--panel); }
    .mem-card.quarantined { border-left:3px solid var(--warn); }
    .mem-card.active { border-left:3px solid var(--ok); }
    .mem-card.superseded, .mem-card.tombstoned { opacity:.65; }
    .mem-content { font-size:13px; }
    .mem-meta { display:flex; gap:5px; flex-wrap:wrap; }
    .mem-meta .tag.status-active { color:var(--ok); background:var(--ok-soft); border-color:transparent; }
    .mem-meta .tag.status-quarantined { color:var(--warn); background:var(--warn-soft); border-color:transparent; }

    /* activity */
    .event { display:grid; gap:3px; padding:9px 11px; border:1px solid var(--line); border-radius:10px; }
    .event-title { font-weight:650; font-size:12.5px; }
    .event-meta { color:var(--muted); font-size:11.5px; }

    /* files */
    .file-row {
      display:flex; align-items:center; gap:10px; padding:10px 12px;
      border:1px solid var(--line); border-radius:10px; background:var(--panel);
      cursor:pointer; text-align:left; width:100%;
    }
    .file-row:hover { border-color:var(--accent); background:var(--accent-soft); }
    .file-icon { font-size:16px; flex:none; }
    .file-name { font-weight:650; font-size:13px; overflow-wrap:anywhere; }
    .file-meta { margin-left:auto; color:var(--muted); font-size:11.5px; white-space:nowrap; flex:none; }
    .files-root { color:var(--muted); font-size:11.5px; padding:2px 2px 6px; overflow-wrap:anywhere; }

    /* markdown viewer */
    .md { font-size:13.5px; line-height:1.6; display:grid; gap:10px; }
    .md .md-h1 { font-size:19px; font-weight:800; letter-spacing:-.01em; }
    .md .md-h2 { font-size:16px; font-weight:750; margin-top:6px; }
    .md .md-h3, .md .md-h4 { font-size:14px; font-weight:700; margin-top:4px; }
    .md p { margin:0; }
    .md ul { margin:0; padding-left:20px; display:grid; gap:4px; }
    .md a { color:var(--accent); }
    .md code { background:var(--panel-2); border:1px solid var(--line); border-radius:5px; padding:1px 5px; font-size:12px; }
    .md pre { font-size:12px; color:var(--ink); }
    .md pre code { border:none; background:none; padding:0; }
    #fileText {
      width:100%; min-height:320px; resize:vertical;
      border:1px solid var(--line-strong); border-radius:10px; padding:12px;
      background:var(--panel-2); outline:none;
      font:12.5px/1.55 ui-monospace, "SF Mono", Menlo, monospace;
    }
    #fileText:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
    pre { margin:0; white-space:pre-wrap; overflow-wrap:break-word; font-size:11.5px; background:var(--panel-2); border-radius:8px; padding:8px 10px; color:var(--muted); }

    /* ---------- settings & connect overlays ---------- */
    .overlay {
      position:fixed; inset:0; z-index:50; display:none;
      align-items:flex-start; justify-content:center; padding:7vh 18px 18px;
      background:rgba(10,14,22,.45); backdrop-filter:blur(3px);
    }
    .overlay.show { display:flex; }
    .sheet { width:min(560px,100%); max-height:84vh; overflow-y:auto; padding:0; }
    .sheet .card-head { position:sticky; top:0; background:var(--panel); border-radius:var(--radius) var(--radius) 0 0; }
    .sheet-body { padding:16px 18px 20px; display:grid; gap:16px; }
    .field { display:grid; gap:5px; }
    .field label { font-size:12px; font-weight:700; color:var(--muted); }
    .field input, .field select {
      border:1px solid var(--line-strong); border-radius:9px; padding:9px 11px; background:var(--panel-2); outline:none; width:100%;
    }
    .field input:focus, .field select:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
    .primary-btn { background:var(--accent); color:var(--accent-ink); border:none; border-radius:10px; padding:10px 16px; font-weight:700; }
    .status-line { font-size:12.5px; color:var(--muted); }
    .status-line.ok { color:var(--ok); } .status-line.bad { color:var(--bad); }
    .check-grid { display:grid; gap:6px; font-size:12.5px; }
    .check-row { display:flex; align-items:center; gap:8px; }
    .section-title { font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
    .divider { border-top:1px solid var(--line); }
    .close-x { margin-left:auto; }

    #connectOverlay .sheet { width:min(440px,100%); }
    .connect-hero { text-align:center; display:grid; gap:6px; justify-items:center; padding-top:6px; }
    .connect-hero .brand-mark { width:44px; height:44px; border-radius:12px; font-size:20px; }
  </style>
</head>
<body>
<header>
  <div class="brand">
    <div class="brand-mark">æ</div>
    <div>aetnamem<small>private assistant · governed memory</small></div>
  </div>
  <div class="header-status">
    <span class="pill" id="pillProvider"><span class="dot" id="dotProvider"></span><span id="pillProviderText">model…</span></span>
    <span class="pill" id="pillAudit"><span class="dot" id="dotAudit"></span><span id="pillAuditText">audit…</span></span>
    <button class="icon-btn" onclick="openSettings()">Settings</button>
  </div>
</header>

<main>
  <section class="card chat-card">
    <div class="card-head">
      <h2>Assistant</h2>
      <span class="sub">runs on your Mac · file writes need your approval</span>
    </div>
    <div id="chat">
      <div class="empty-chat" id="emptyChat">
        <div class="big">&#128075;</div>
        <div><strong>Everything stays on this Mac.</strong><br>
        <span style="color:var(--muted)">The assistant remembers what you tell it and asks before touching your files.</span></div>
        <div class="chips">
          <button class="chip" onclick="useSuggestion(this)">Remember: my weekly report lives in report.md</button>
          <button class="chip" onclick="useSuggestion(this)">What do you remember about me?</button>
          <button class="chip" onclick="useSuggestion(this)">Draft my weekly report into report.md</button>
        </div>
      </div>
    </div>
    <div class="composer">
      <textarea id="chatInput" rows="1" placeholder="Message your assistant…"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendChat()">Send</button>
    </div>
  </section>

  <section class="card side-card">
    <div class="tabs">
      <button class="tab active" id="tab-approvals" onclick="showPanel('approvals')">Approvals <span class="badge" id="approvalBadge"></span></button>
      <button class="tab" id="tab-files" onclick="showPanel('files')">Files</button>
      <button class="tab" id="tab-memory" onclick="showPanel('memory')">Memory</button>
      <button class="tab" id="tab-activity" onclick="showPanel('activity')">Activity</button>
    </div>
    <div id="panel-approvals" class="panel active">
      <div id="actions"></div>
    </div>
    <div id="panel-files" class="panel">
      <div class="files-root" id="filesRoot"></div>
      <div id="files" style="display:grid;gap:8px"></div>
    </div>
    <div id="panel-memory" class="panel">
      <div class="mem-toolbar">
        <input id="memorySearch" placeholder="Search memory…" oninput="renderMemory()">
        <select id="memoryStatusFilter" onchange="renderMemory()">
          <option value="">All</option>
          <option value="active">Active</option>
          <option value="quarantined">Needs review</option>
          <option value="superseded">Replaced</option>
          <option value="tombstoned">Forgotten</option>
        </select>
      </div>
      <div id="memory" style="display:grid;gap:8px"></div>
    </div>
    <div id="panel-activity" class="panel">
      <div id="audit" style="display:grid;gap:8px"></div>
    </div>
  </section>
</main>

<!-- settings -->
<div class="overlay" id="settingsOverlay">
  <div class="card sheet">
    <div class="card-head">
      <h2>Settings</h2>
      <button class="icon-btn close-x" onclick="closeSettings()">Done</button>
    </div>
    <div class="sheet-body">
      <div class="section-title">AI model</div>
      <div class="field">
        <label for="providerKind">Provider</label>
        <select id="providerKind" onchange="providerKindChanged()">
          <option value="local">On this Mac (Ollama) — private, free</option>
          <option value="echo">Offline echo (no model)</option>
          <option value="openai">OpenAI</option>
          <option value="deepseek">DeepSeek</option>
          <option value="openai-compatible">OpenAI-compatible endpoint</option>
        </select>
      </div>
      <div class="field"><label for="providerModel">Model</label><input id="providerModel" value="qwen3:1.7b"></div>
      <div class="field" id="fieldBase"><label for="providerBase">Base URL</label><input id="providerBase" placeholder="http://localhost:11434"></div>
      <div class="field" id="fieldKey"><label for="providerKey">API key</label><input id="providerKey" type="password" placeholder="Only for cloud providers"></div>
      <button class="primary-btn" onclick="saveProvider()">Save model settings</button>
      <div class="status-line" id="providerStatus"></div>

      <div class="divider"></div>
      <div class="section-title">System check</div>
      <div class="check-grid" id="checks">Checking…</div>

      <div class="divider"></div>
      <div class="section-title">Data &amp; security</div>
      <div class="check-grid" id="security">Checking…</div>

      <div class="divider"></div>
      <details>
        <summary class="section-title" style="cursor:pointer">Advanced: access tokens</summary>
        <div style="display:grid;gap:12px;padding-top:12px">
          <div class="status-line">Tokens are filled automatically when the app launches. Only paste them here if you opened this page by hand.</div>
          <div class="field"><label for="agentToken">Agent token</label><input id="agentToken" type="password" autocomplete="off"></div>
          <div class="field"><label for="reviewerToken">Reviewer token</label><input id="reviewerToken" type="password" autocomplete="off"></div>
          <button class="icon-btn" onclick="saveTokens()">Save tokens</button>
        </div>
      </details>
    </div>
  </div>
</div>

<!-- file viewer / editor -->
<div class="overlay" id="fileOverlay">
  <div class="card sheet" style="width:min(760px,100%)">
    <div class="card-head">
      <h2 id="fileTitle">file</h2>
      <span class="sub" id="fileSaved"></span>
      <button class="icon-btn close-x" id="fileEditBtn" onclick="toggleFileEdit()">Edit</button>
      <button class="icon-btn" onclick="closeFile()">Close</button>
    </div>
    <div class="sheet-body">
      <div id="fileView" class="md"></div>
      <div id="fileEditor" style="display:none;gap:10px">
        <textarea id="fileText" spellcheck="false"></textarea>
        <button class="primary-btn" onclick="saveFile()">Save changes</button>
      </div>
      <div class="status-line" id="fileStatus"></div>
    </div>
  </div>
</div>

<!-- connect (only when no tokens) -->
<div class="overlay" id="connectOverlay">
  <div class="card sheet">
    <div class="sheet-body">
      <div class="connect-hero">
        <div class="brand-mark">æ</div>
        <h2 style="margin:6px 0 0">Connect to aetnamem</h2>
        <div class="status-line">The launcher normally signs you in automatically.<br>
        Relaunch <b>aetnamem-desktop.command</b>, or paste the tokens it printed.</div>
      </div>
      <div class="field"><label for="connectAgent">Agent token</label><input id="connectAgent" type="password" autocomplete="off"></div>
      <div class="field"><label for="connectReviewer">Reviewer token</label><input id="connectReviewer" type="password" autocomplete="off"></div>
      <button class="primary-btn" onclick="connectManually()">Connect</button>
      <div class="status-line bad" id="connectError"></div>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
const subject = "default";
let memoryRecords = [];
let sending = false;

/* ---------- token bootstrap: URL fragment -> localStorage ---------- */
function adoptTokensFromHash(){
  if (!location.hash) return;
  const params = new URLSearchParams(location.hash.slice(1));
  const agent = params.get("agent"), reviewer = params.get("reviewer");
  if (agent) localStorage.agentToken = agent;
  if (reviewer) localStorage.reviewerToken = reviewer;
  if (agent || reviewer) history.replaceState(null, "", location.pathname);
}
function hasTokens(){ return !!(localStorage.agentToken && localStorage.reviewerToken); }
function connectManually(){
  const agent = $("connectAgent").value.trim(), reviewer = $("connectReviewer").value.trim();
  if (!agent || !reviewer) { $("connectError").textContent = "Both tokens are required."; return; }
  localStorage.agentToken = agent; localStorage.reviewerToken = reviewer;
  $("connectOverlay").classList.remove("show");
  refreshAll();
}
function saveTokens(){
  localStorage.agentToken = $("agentToken").value.trim();
  localStorage.reviewerToken = $("reviewerToken").value.trim();
  refreshAll();
}

/* ---------- api ---------- */
async function api(path, opts={}){
  const role = opts.role || "agent";
  const token = role === "reviewer" ? localStorage.reviewerToken : localStorage.agentToken;
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: {"Authorization":"Bearer "+token, "Content-Type":"application/json"},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(()=>({error:"invalid response"}));
  if (!res.ok) {
    if (res.status === 401) showConnect();
    throw new Error(data.error || res.statusText);
  }
  return data;
}
function showConnect(){ $("connectOverlay").classList.add("show"); }

/* ---------- header status ---------- */
async function refreshStatus(){
  try {
    const [p, c] = await Promise.all([api("/provider"), api("/system-check")]);
    let cls = "ok", text = p.model + " · on this Mac";
    if (p.kind === "echo") { cls = "warn"; text = "offline mode — no model"; }
    else if (p.kind === "local" && !c.ollama_api) { cls = "bad"; text = p.model + " · Ollama not running"; }
    else if (p.kind !== "local") { text = p.model + " · " + p.kind; }
    $("dotProvider").className = "dot " + cls;
    $("pillProviderText").textContent = text;
    window._systemCheck = c;
    renderChecks(c);
  } catch (e) {
    $("dotProvider").className = "dot bad";
    $("pillProviderText").textContent = "not connected";
  }
  try {
    const v = await api("/verify?subject=" + encodeURIComponent(subject));
    $("dotAudit").className = "dot " + (v.audit_chain_valid ? "ok" : "bad");
    $("pillAuditText").textContent = v.audit_chain_valid ? "audit chain verified" : "audit chain broken";
  } catch (e) {
    $("dotAudit").className = "dot"; $("pillAuditText").textContent = "audit unknown";
  }
}
function renderChecks(c){
  const row = (good, label, extra) =>
    `<div class="check-row"><span class="dot ${good ? 'ok' : 'warn'}"></span>${label}${extra ? ' — <span style="color:var(--muted)">'+extra+'</span>' : ''}</div>`;
  $("checks").innerHTML =
    row(c.mac_only_supported, "macOS", c.platform) +
    row(true, "Python " + c.python) +
    row(c.has_min_disk_1gb, "Free disk space", c.has_min_disk_1gb ? "OK" : "less than 1 GB") +
    row(c.ollama_cli, "Ollama installed", c.ollama_cli ? "" : "install from ollama.com") +
    row(c.ollama_api, "Local model service", c.ollama_api ? "running" : "not running") +
    `<div class="check-row"><span class="dot ok"></span>Recommended model — <code style="margin-left:4px">${c.recommended_local_model}</code></div>`;
  renderSecurity(c);
}
function renderSecurity(c){
  const row = (good, label, extra) =>
    `<div class="check-row"><span class="dot ${good ? 'ok' : 'warn'}"></span>${label}${extra ? ' — <span style="color:var(--muted);overflow-wrap:anywhere">'+escapeHtml(extra)+'</span>' : ''}</div>`;
  let html = row(true, "Runs only on this Mac", "loopback service, nothing leaves your machine");
  if (c.workspace) html += row(true, "Assistant can only write inside", c.workspace);
  if (c.db_path) html += row(true, "Live memory database (while app is open)", c.db_path);
  if (c.db_sealed_at_rest) {
    html += row(true, "Encrypted when you quit", "sealed to " + c.db_sealed_path);
    html += row(true, "Encryption key", "stored in your macOS Keychain");
  } else {
    html += row(false, "Encryption at rest", "off — database stays plaintext on disk");
  }
  $("security").innerHTML = html;
}

/* ---------- settings ---------- */
function openSettings(){
  $("agentToken").value = localStorage.agentToken || "";
  $("reviewerToken").value = localStorage.reviewerToken || "";
  $("settingsOverlay").classList.add("show");
  refreshStatus();
}
function closeSettings(){ $("settingsOverlay").classList.remove("show"); }
function providerKindChanged(){
  const kind = $("providerKind").value;
  $("fieldKey").style.display = (kind === "local" || kind === "echo") ? "none" : "";
  $("fieldBase").style.display = (kind === "echo") ? "none" : "";
  if (kind === "local" && !$("providerModel").value) $("providerModel").value = "qwen3:1.7b";
}
async function saveProvider(){
  try {
    const p = await api("/provider", {role:"reviewer", method:"POST", body:{
      kind: $("providerKind").value, model: $("providerModel").value,
      base_url: $("providerBase").value, api_key: $("providerKey").value,
    }});
    $("providerStatus").className = "status-line ok";
    $("providerStatus").textContent = "Saved: " + p.kind + " / " + p.model + (p.base_url ? " / " + p.base_url : "");
    refreshStatus();
  } catch (e) {
    $("providerStatus").className = "status-line bad";
    $("providerStatus").textContent = e.message;
  }
}
async function refreshProvider(){
  try {
    const p = await api("/provider");
    $("providerKind").value = p.kind;
    $("providerModel").value = p.model;
    $("providerBase").value = p.base_url || "";
    providerKindChanged();
  } catch (e) {}
}

/* ---------- chat ---------- */
function useSuggestion(el){ $("chatInput").value = el.textContent; $("chatInput").focus(); }
function appendMsg(cls, text, toolHtml){
  const empty = $("emptyChat"); if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  if (toolHtml) {
    const tool = document.createElement("div");
    tool.className = "tool";
    tool.innerHTML = toolHtml;
    div.appendChild(tool);
  }
  $("chat").appendChild(div);
  $("chat").scrollTop = $("chat").scrollHeight;
  return div;
}
async function sendChat(){
  const text = $("chatInput").value.trim();
  if (!text || sending) return;
  sending = true; $("sendBtn").disabled = true;
  appendMsg("user", text);
  $("chatInput").value = "";
  const typing = document.createElement("div");
  typing.className = "typing"; typing.textContent = "Assistant is thinking…";
  $("chat").appendChild(typing); $("chat").scrollTop = $("chat").scrollHeight;
  try {
    const r = await api("/chat", {role:"reviewer", method:"POST", body:{subject_id:subject, message:text, session_id:"desktop"}});
    typing.remove();
    let toolHtml = "";
    if (r.tool_result) {
      const t = r.tool_result;
      if (t.status === "awaiting_approval") {
        toolHtml = 'Action staged — <b>waiting for your approval</b> in the Approvals tab.';
      } else if (t.status === "executed") {
        toolHtml = 'Used a governed tool &#10003;';
      } else {
        toolHtml = 'Tool ' + escapeHtml(t.status || "") + (t.message ? ": " + escapeHtml(t.message) : "");
      }
    }
    appendMsg("assistant", friendlyReply(r.reply), toolHtml);
    await refreshActions(); await refreshMemory(); refreshFiles();
  } catch (e) {
    typing.remove();
    appendMsg("notice", "Error: " + e.message);
  } finally {
    sending = false; $("sendBtn").disabled = false;
  }
}
function friendlyReply(text){
  const t = (text || "").trim();
  if (t.startsWith("{")) {
    try {
      const j = JSON.parse(t);
      if (j.tool) return "Let me use the \\u201c" + j.tool.replace(/_/g, " ") + "\\u201d tool for that.";
    } catch (e) {}
  }
  return t || "(no reply)";
}
$("chatInput").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

/* ---------- tabs ---------- */
function showPanel(name){
  for (const p of ["approvals","files","memory","activity"]) {
    $("panel-"+p).classList.toggle("active", p === name);
    $("tab-"+p).classList.toggle("active", p === name);
  }
  if (name === "activity") refreshAudit();
  if (name === "memory") refreshMemory();
  if (name === "files") refreshFiles();
}

/* ---------- files ---------- */
let currentFile = null;
async function refreshFiles(){
  try {
    const r = await api("/files");
    $("filesRoot").textContent = "Workspace: " + r.root;
    const box = $("files");
    box.innerHTML = "";
    if (!r.files.length) {
      box.innerHTML = "<div class='hint'>The workspace is empty.<br>Files the assistant writes (after your approval) appear here.</div>";
      return;
    }
    for (const f of r.files) {
      const btn = document.createElement("button");
      btn.className = "file-row";
      const icon = /\\.(md|markdown)$/i.test(f.path) ? "&#128221;" : "&#128196;";
      btn.innerHTML =
        `<span class="file-icon">${icon}</span>` +
        `<span class="file-name">${escapeHtml(f.path)}</span>` +
        `<span class="file-meta">${fmtSize(f.size)} · ${escapeHtml(fmtTime(f.modified))}</span>`;
      btn.onclick = () => openFile(f.path);
      box.appendChild(btn);
    }
  } catch (e) { $("files").innerHTML = "<div class='hint'>" + escapeHtml(e.message) + "</div>"; }
}
async function openFile(path){
  try {
    const r = await api("/files/content?path=" + encodeURIComponent(path));
    currentFile = r;
    $("fileTitle").textContent = r.path;
    $("fileStatus").textContent = "";
    $("fileSaved").textContent = "";
    setFileEditing(false);
    $("fileOverlay").classList.add("show");
  } catch (e) { alert(e.message); }
}
function renderFileView(){
  const view = $("fileView");
  if (/\\.(md|markdown)$/i.test(currentFile.path)) view.innerHTML = renderMarkdown(currentFile.content);
  else view.innerHTML = "<pre>" + escapeHtml(currentFile.content) + "</pre>";
  if (!currentFile.content.trim()) view.innerHTML = "<div class='hint'>(empty file)</div>";
}
function setFileEditing(editing){
  $("fileEditor").style.display = editing ? "grid" : "none";
  $("fileView").style.display = editing ? "none" : "grid";
  $("fileEditBtn").textContent = editing ? "Preview" : "Edit";
  if (editing) { $("fileText").value = currentFile.content; $("fileText").focus(); }
  else renderFileView();
}
function toggleFileEdit(){
  const editing = $("fileEditor").style.display !== "grid";
  if (!editing) currentFile.content = $("fileText").value;
  setFileEditing(editing);
}
async function saveFile(){
  try {
    currentFile.content = $("fileText").value;
    await api("/files/content", {role:"reviewer", method:"POST", body:{path:currentFile.path, content:currentFile.content, session_id:"desktop"}});
    $("fileStatus").className = "status-line ok";
    $("fileStatus").textContent = "Saved.";
    $("fileSaved").textContent = "saved " + new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
    setFileEditing(false);
    refreshFiles();
  } catch (e) {
    $("fileStatus").className = "status-line bad";
    $("fileStatus").textContent = "Save failed: " + e.message;
  }
}
function closeFile(){ $("fileOverlay").classList.remove("show"); currentFile = null; }
function fmtSize(n){
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n/1024).toFixed(1) + " KB";
  return (n/1048576).toFixed(1) + " MB";
}

/* minimal safe markdown: escape first, then transform */
function mdInline(s){
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\\*\\*([^*]+)\\*\\*/g, "<b>$1</b>")
    .replace(/\\*([^*]+)\\*/g, "<i>$1</i>")
    .replace(/\\[([^\\]]+)\\]\\((https?:[^)\\s]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function renderMarkdown(src){
  const lines = src.split(/\\r?\\n/);
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push("<pre><code>" + escapeHtml(buf.join("\\n")) + "</code></pre>");
      continue;
    }
    const heading = line.match(/^(#{1,4})\\s+(.*)$/);
    if (heading) {
      out.push(`<div class="md-h${heading[1].length}">` + mdInline(escapeHtml(heading[2])) + "</div>");
      i++;
      continue;
    }
    if (/^\\s*[-*]\\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\\s*[-*]\\s+/.test(lines[i])) {
        items.push("<li>" + mdInline(escapeHtml(lines[i].replace(/^\\s*[-*]\\s+/, ""))) + "</li>");
        i++;
      }
      out.push("<ul>" + items.join("") + "</ul>");
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\\s|```|\\s*[-*]\\s)/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    out.push("<p>" + mdInline(escapeHtml(para.join(" "))) + "</p>");
  }
  return out.join("");
}

/* ---------- approvals ---------- */
async function refreshActions(){
  try {
    const [r, g] = await Promise.all([
      api("/actions?subject=" + encodeURIComponent(subject)),
      api("/graph/merges?subject=" + encodeURIComponent(subject) + "&status=pending")
    ]);
    const pending = (r.actions || []).filter(a => a.state === "awaiting_approval");
    const graphMerges = g.merges || [];
    const badge = $("approvalBadge");
    badge.textContent = pending.length + graphMerges.length;
    badge.classList.toggle("show", pending.length + graphMerges.length > 0);
    const box = $("actions");
    box.innerHTML = "";
    if (!pending.length && !graphMerges.length) {
      box.innerHTML = "<div class='hint'>No actions waiting for approval.<br>When the assistant wants to change a file, it will ask here first.</div>";
      return;
    }
    for (const merge of graphMerges) box.appendChild(graphMergeCard(merge));
    for (const a of pending) box.appendChild(await approvalCard(a));
  } catch (e) {
    $("actions").innerHTML = "<div class='hint'>" + escapeHtml(e.message) + "</div>";
  }
}
function graphMergeCard(merge){
  const div = document.createElement("div");
  div.className = "approval";
  const left = merge.left_canonical || merge.left_entity;
  const right = merge.right_canonical || merge.right_entity;
  div.innerHTML =
    `<div class="approval-head">Entity merge review</div>` +
    `<div class="approval-body"><div><b>${escapeHtml(left)}</b> and <b>${escapeHtml(right)}</b></div>` +
    `<div class="approval-meta">${escapeHtml(merge.reason || "exact alias match")} · confidence ${Number(merge.confidence || 0).toFixed(2)}</div>` +
    `<label class="approval-meta">Keep as <select class="merge-winner">` +
    `<option value="${escapeHtml(merge.left_entity)}">${escapeHtml(left)}</option>` +
    `<option value="${escapeHtml(merge.right_entity)}">${escapeHtml(right)}</option>` +
    `</select></label></div>` +
    `<div class="approval-actions"><button class="btn approve">Merge</button><button class="btn deny">Keep separate</button></div>`;
  div.querySelector(".approve").onclick = async () => {
    try {
      await api(`/graph/merges/${encodeURIComponent(merge.id)}/approve`, {
        role:"reviewer", method:"POST",
        body:{subject_id:subject, winner_entity:div.querySelector(".merge-winner").value, actor:"local-user"}
      });
      appendMsg("notice", "Entities merged. The decision remains reversible.");
    } catch (e) { appendMsg("notice", "Merge failed: " + e.message); }
    refreshActions(); refreshMemory(); refreshAudit();
  };
  div.querySelector(".deny").onclick = async () => {
    try {
      await api(`/graph/merges/${encodeURIComponent(merge.id)}/reject`, {
        role:"reviewer", method:"POST", body:{subject_id:subject, actor:"local-user"}
      });
    } catch (e) { appendMsg("notice", "Reject failed: " + e.message); }
    refreshActions(); refreshAudit();
  };
  return div;
}
async function approvalCard(a){
  const id = a.id || a.transaction_id;
  let detail = a;
  try { detail = await api("/actions/" + encodeURIComponent(id)); } catch (e) {}
  const ops = detail.operations || [];
  const div = document.createElement("div");
  div.className = "approval";
  const opsHtml = ops.length
    ? ops.map(op =>
        `<div class="op"><span class="tag">${escapeHtml(op.adapter || "")}</span>` +
        `<b>${escapeHtml((op.operation || "").replace(/_/g, " "))}</b>` +
        `<span class="tag effect">${escapeHtml(op.effect_class || "")}</span></div>`
      ).join("")
    : `<div class="op"><b>Proposed action</b></div>`;
  div.innerHTML =
    `<div class="approval-head">&#9888;&#65039; Approval needed</div>` +
    `<div class="approval-body">${opsHtml}` +
    `<div class="approval-meta">by ${escapeHtml(detail.actor_id || "assistant")} · ${escapeHtml(fmtTime(detail.created_at))} · ${escapeHtml(id)}</div>` +
    `<details class="raw"><summary>Full plan details</summary><pre>${escapeHtml(JSON.stringify(detail, null, 2))}</pre></details></div>` +
    `<div class="approval-actions"><button class="btn approve">Approve &amp; run</button><button class="btn deny">Deny</button></div>`;
  div.querySelector(".approve").onclick = async () => {
    try {
      await api(`/actions/${id}/approve`, {role:"reviewer", method:"POST", body:{approver_label:"local-user"}});
      await api(`/actions/${id}/commit`, {role:"reviewer", method:"POST"});
      appendMsg("notice", "Approved and completed.");
    } catch (e) { appendMsg("notice", "Approve failed: " + e.message); }
    refreshActions(); refreshAudit(); refreshFiles();
  };
  div.querySelector(".deny").onclick = async () => {
    try { await api(`/actions/${id}/deny`, {role:"reviewer", method:"POST", body:{actor:"local-user"}}); }
    catch (e) { appendMsg("notice", "Deny failed: " + e.message); }
    refreshActions();
  };
  return div;
}

/* ---------- memory ---------- */
async function refreshMemory(){
  try {
    const r = await api("/memory?subject=" + encodeURIComponent(subject) + "&include_inactive=1");
    memoryRecords = r.records || [];
    renderMemory();
  } catch (e) { $("memory").innerHTML = "<div class='hint'>" + escapeHtml(e.message) + "</div>"; }
}
function renderMemory(){
  const q = ($("memorySearch").value || "").trim().toLowerCase();
  const status = $("memoryStatusFilter").value || "";
  const filtered = memoryRecords.filter(m => {
    const hay = [m.content, m.fact_key, m.status, m.source_type, m.trust_tier, m.id].join(" ").toLowerCase();
    return (!q || hay.includes(q)) && (!status || m.status === status);
  });
  const box = $("memory");
  box.innerHTML = "";
  if (!filtered.length) {
    box.innerHTML = "<div class='hint'>Nothing remembered yet.<br>Tell the assistant something worth keeping.</div>";
    return;
  }
  const groups = [
    ["Active", "active"],
    ["Needs review", "quarantined"],
    ["Replaced", "superseded"],
    ["Forgotten", "tombstoned"],
  ];
  const known = new Set(groups.map(g => g[1]));
  for (const [label, groupStatus] of groups.concat([["Other", null]])) {
    const records = filtered.filter(m => groupStatus ? m.status === groupStatus : !known.has(m.status));
    if (!records.length) continue;
    const title = document.createElement("div");
    title.className = "mem-group-title";
    title.innerHTML = `${label} <span class="count">${records.length}</span>`;
    box.appendChild(title);
    for (const m of records.sort((a,b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))) {
      box.appendChild(memoryCard(m));
    }
  }
}
function memoryCard(m){
  const div = document.createElement("div");
  div.className = "mem-card " + (m.status || "");
  const confidence = m.confidence == null ? "" : `<span class="tag">conf ${Number(m.confidence).toFixed(2)}</span>`;
  div.innerHTML =
    `<div class="mem-content">${escapeHtml(m.content || "(content purged)")}</div>` +
    `<div class="mem-meta">` +
      `<span class="tag status-${escapeHtml(m.status || "")}">${escapeHtml(m.status || "")}</span>` +
      `<span class="tag">${escapeHtml((m.fact_key || m.scope || "general").replace(/_/g, " "))}</span>` +
      `<span class="tag">${escapeHtml(m.source_type || "")}</span>` +
      `<span class="tag">${escapeHtml(m.trust_tier || "")}</span>` + confidence +
    `</div>` +
    `<details class="raw"><summary>Details</summary><pre>${escapeHtml(JSON.stringify(m, null, 2))}</pre></details>`;
  return div;
}

/* ---------- activity ---------- */
async function refreshAudit(){
  try {
    const r = await api("/audit?subject=" + encodeURIComponent(subject));
    const log = (r.audit_log || []).slice().reverse().slice(0, 40);
    const box = $("audit");
    box.innerHTML = log.length ? "" : "<div class='hint'>No activity yet.</div>";
    for (const e of log) {
      const div = document.createElement("div");
      div.className = "event";
      div.innerHTML =
        `<div class="event-title">${escapeHtml((e.event_type || "").replace(/[._]/g, " "))}</div>` +
        `<div class="event-meta">#${e.sequence} · ${escapeHtml(e.actor || "")} · ${escapeHtml(fmtTime(e.created_at))}</div>` +
        `<details class="raw"><summary>Payload</summary><pre>${escapeHtml(JSON.stringify(e.payload || {}, null, 2))}</pre></details>`;
      box.appendChild(div);
    }
  } catch (e) { $("audit").innerHTML = "<div class='hint'>" + escapeHtml(e.message) + "</div>"; }
}

/* ---------- helpers ---------- */
function fmtTime(value){
  if (!value) return "";
  const d = new Date(value);
  return isNaN(d) ? String(value) : d.toLocaleString([], {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit"});
}
function escapeHtml(value){
  return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

/* ---------- boot ---------- */
async function refreshAll(){
  await refreshStatus();
  await refreshProvider();
  await refreshActions();
  await refreshMemory();
}
adoptTokensFromHash();
if (!hasTokens()) { showConnect(); } else { refreshAll(); }
setInterval(() => { if (hasTokens() && !document.hidden) { refreshActions(); } }, 5000);
setInterval(() => { if (hasTokens() && !document.hidden) { refreshStatus(); } }, 20000);
</script>
</body>
</html>"""
