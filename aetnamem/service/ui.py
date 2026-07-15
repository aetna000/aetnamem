APP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>aetnamem desktop</title>
  <style>
    :root { color-scheme: light dark; --line:#d8dde6; --ink:#18202a; --muted:#647084; --ok:#16794c; --warn:#a35d00; --bad:#b3261e; --bg:#f7f9fc; --panel:#fff; }
    @media (prefers-color-scheme: dark) { :root { --line:#303846; --ink:#eef3fb; --muted:#9aa7bb; --bg:#10141b; --panel:#171d26; } }
    * { box-sizing: border-box; }
    body { margin:0; font:14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }
    header { padding:18px 24px; border-bottom:1px solid var(--line); background:var(--panel); display:flex; justify-content:space-between; gap:16px; align-items:center; }
    h1 { margin:0; font-size:20px; }
    main { max-width:1180px; margin:0 auto; padding:20px; display:grid; grid-template-columns: 340px 1fr; gap:16px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }
    h2 { margin:0 0 12px; font-size:15px; }
    label { display:block; font-weight:600; margin:10px 0 5px; }
    input, textarea, select, button { width:100%; font:inherit; border-radius:6px; border:1px solid var(--line); padding:9px 10px; background:transparent; color:var(--ink); }
    textarea { min-height:92px; resize:vertical; }
    button { background:#2457d6; color:white; border-color:#2457d6; font-weight:700; cursor:pointer; }
    button.secondary { background:transparent; color:var(--ink); border-color:var(--line); }
    button.danger { background:var(--bad); border-color:var(--bad); }
    .stack { display:grid; gap:12px; }
    .row { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .muted { color:var(--muted); }
    .pill { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:3px 8px; margin:2px; }
    .card { border:1px solid var(--line); border-radius:8px; padding:10px; display:grid; gap:5px; }
    .card-title { font-weight:700; }
    .meta { color:var(--muted); font-size:12px; display:flex; flex-wrap:wrap; gap:6px; }
    .meta span { border:1px solid var(--line); border-radius:999px; padding:2px 7px; }
    .tabs { display:flex; gap:8px; margin-bottom:12px; }
    .tabs button { width:auto; padding:7px 10px; background:transparent; color:var(--ink); border-color:var(--line); }
    .tabs button.active { background:#2457d6; color:white; border-color:#2457d6; }
    .panel { display:none; }
    .panel.active { display:block; }
    .toolbar { display:grid; grid-template-columns: 1fr 180px; gap:8px; margin-bottom:12px; }
    .group { border:1px solid var(--line); border-radius:8px; padding:10px; display:grid; gap:10px; }
    .group-head { display:flex; justify-content:space-between; align-items:center; gap:8px; font-weight:800; }
    .topic { display:grid; gap:8px; }
    .topic-title { color:var(--muted); font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:.04em; }
    .count { color:var(--muted); font-size:12px; border:1px solid var(--line); border-radius:999px; padding:2px 7px; }
    details summary { cursor:pointer; color:var(--muted); font-size:12px; }
    .ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
    pre { white-space:pre-wrap; overflow:auto; background:rgba(120,130,150,.11); padding:10px; border-radius:6px; }
    .chat { min-height:280px; max-height:460px; overflow:auto; border:1px solid var(--line); border-radius:8px; padding:10px; }
    .msg { margin:0 0 10px; padding:9px 10px; border-radius:8px; background:rgba(120,130,150,.11); }
    .user { border-left:3px solid #2457d6; }
    .assistant { border-left:3px solid #16794c; }
    @media (max-width: 860px) { main { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<header>
  <div><h1>aetnamem desktop</h1><div class="muted">Local assistant with governed memory and approval-gated tools</div></div>
  <button class="secondary" style="width:auto" onclick="refreshAll()">Refresh</button>
</header>
<main>
  <div class="stack">
    <section>
      <h2>1. Connect</h2>
      <label>Agent token</label><input id="agentToken" type="password">
      <label>Reviewer token</label><input id="reviewerToken" type="password">
      <button onclick="saveTokens()">Save tokens</button>
      <p class="muted">Tokens are printed by <code>python -m aetnamem.service</code>. A packaged Mac app should hide this.</p>
    </section>
    <section>
      <h2>2. Mac check</h2>
      <div id="checks" class="muted">Not checked yet.</div>
      <button class="secondary" onclick="loadChecks()">Run check</button>
    </section>
    <section>
      <h2>3. AI provider</h2>
      <label>Provider</label>
      <select id="providerKind">
        <option value="local">Local light (Ollama)</option>
        <option value="echo">Offline echo</option>
        <option value="openai">OpenAI</option>
        <option value="deepseek">DeepSeek</option>
        <option value="openai-compatible">OpenAI-compatible</option>
      </select>
      <label>Model</label><input id="providerModel" value="qwen3:1.7b">
      <label>Base URL</label><input id="providerBase" placeholder="http://localhost:11434 for Ollama">
      <label>API key</label><input id="providerKey" type="password" placeholder="Remote providers only">
      <button onclick="saveProvider()">Save provider</button>
      <p class="muted">For a 12 GB M1 laptop: install Ollama, run <code>ollama pull qwen3:1.7b</code>, then use Local light.</p>
      <div id="providerStatus" class="muted"></div>
    </section>
  </div>
  <div class="stack">
    <section>
      <h2>Memory and audit</h2>
      <div class="tabs">
        <button id="tab-memory" class="active" onclick="showPanel('memory')">Memory</button>
        <button id="tab-audit" onclick="showPanel('audit')">Audit</button>
        <button id="tab-checksPanel" onclick="showPanel('checksPanel')">Checks</button>
      </div>
      <div id="panel-memory" class="panel active">
        <div class="toolbar">
          <input id="memorySearch" placeholder="Search remembered facts" oninput="renderMemory()">
          <select id="memoryStatusFilter" onchange="renderMemory()">
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="quarantined">Needs review</option>
            <option value="superseded">Replaced</option>
            <option value="tombstoned">Forgotten</option>
          </select>
        </div>
        <div id="memory" class="stack"></div>
      </div>
      <div id="panel-audit" class="panel">
        <div id="audit" class="stack"></div>
      </div>
      <div id="panel-checksPanel" class="panel">
        <div id="verifyStatus" class="muted">Not checked yet.</div>
        <button class="secondary" onclick="refreshVerify()">Verify audit chain</button>
      </div>
    </section>
    <section>
      <h2>Assistant</h2>
      <div id="chat" class="chat"></div>
      <label>Ask for help</label>
      <textarea id="chatInput" placeholder="Example: remember my weekly report goes in report.md, then draft it."></textarea>
      <button onclick="sendChat()">Send</button>
    </section>
    <section>
      <h2>Pending approvals</h2>
      <div id="actions" class="stack"></div>
    </section>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
const subject = "default";
let memoryRecords = [];
function saveTokens(){ localStorage.agentToken=$("agentToken").value; localStorage.reviewerToken=$("reviewerToken").value; refreshAll(); }
function loadTokens(){ $("agentToken").value=localStorage.agentToken||""; $("reviewerToken").value=localStorage.reviewerToken||""; }
async function api(path, opts={}){
  const role = opts.role || "agent";
  const token = role === "reviewer" ? localStorage.reviewerToken : localStorage.agentToken;
  const res = await fetch(path, {method:opts.method||"GET", headers:{"Authorization":"Bearer "+token, "Content-Type":"application/json"}, body:opts.body?JSON.stringify(opts.body):undefined});
  const data = await res.json().catch(()=>({error:"invalid response"}));
  if(!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
async function loadChecks(){
  try {
    const c = await api("/system-check");
    $("checks").innerHTML = `<div class="${c.mac_only_supported?'ok':'bad'}">macOS: ${c.mac_only_supported?'yes':'no'}</div><div>Python: ${c.python}</div><div class="${c.has_min_disk_1gb?'ok':'bad'}">1 GB disk: ${c.has_min_disk_1gb?'yes':'no'}</div><div class="${c.ollama_cli?'ok':'warn'}">Ollama CLI: ${c.ollama_cli?'installed':'not found'}</div><div class="${c.ollama_api?'ok':'warn'}">Ollama API: ${c.ollama_api?'running':'not running'}</div><div>Light model: <code>${c.recommended_local_model}</code></div>`;
  } catch(e) { $("checks").textContent=e.message; }
}
async function saveProvider(){
  try {
    const p = await api("/provider", {role:"reviewer", method:"POST", body:{kind:$("providerKind").value, model:$("providerModel").value, base_url:$("providerBase").value, api_key:$("providerKey").value}});
    $("providerStatus").textContent = `${p.kind} / ${p.model}${p.base_url ? ' / '+p.base_url : ''} / key ${p.api_key_configured?'set':'not needed'}`;
  } catch(e) { $("providerStatus").textContent=e.message; }
}
async function sendChat(){
  const text = $("chatInput").value.trim(); if(!text) return;
  appendMsg("user", text); $("chatInput").value="";
  try {
    const r = await api("/chat", {role:"reviewer", method:"POST", body:{subject_id:subject, message:text, session_id:"desktop"}});
    appendMsg("assistant", r.reply + (r.tool_result ? "\\n\\nTool: " + JSON.stringify(r.tool_result, null, 2) : ""));
    await refreshActions(); await refreshMemory();
  } catch(e) { appendMsg("assistant", "Error: " + e.message); }
}
function appendMsg(cls, text){ const div=document.createElement("div"); div.className="msg "+cls; div.textContent=text; $("chat").appendChild(div); $("chat").scrollTop=$("chat").scrollHeight; }
function showPanel(name){
  for (const p of ["memory","audit","checksPanel"]) {
    $("panel-"+p).classList.toggle("active", p===name);
    $("tab-"+p).classList.toggle("active", p===name);
  }
}
async function refreshActions(){
  try {
    const r = await api("/actions?subject="+encodeURIComponent(subject));
    const pending = r.actions.filter(a => a.state === "awaiting_approval");
    $("actions").innerHTML = pending.length ? "" : "<div class='muted'>No pending approvals.</div>";
    for (const a of pending) {
      const item=document.createElement("div"); item.className="stack"; item.innerHTML=`<pre>${JSON.stringify(a,null,2)}</pre><div class='row'><button>Approve + commit</button><button class='danger'>Deny</button></div>`;
      item.querySelector("button").onclick=async()=>{ await api(`/actions/${a.transaction_id}/approve`,{role:"reviewer",method:"POST",body:{approver_label:"local-user"}}); await api(`/actions/${a.transaction_id}/commit`,{role:"reviewer",method:"POST"}); refreshActions(); };
      item.querySelector(".danger").onclick=async()=>{ await api(`/actions/${a.transaction_id}/deny`,{role:"reviewer",method:"POST",body:{actor:"local-user"}}); refreshActions(); };
      $("actions").appendChild(item);
    }
  } catch(e) { $("actions").textContent=e.message; }
}
async function refreshMemory(){
  try {
    const r = await api("/memory?subject="+encodeURIComponent(subject)+"&include_inactive=1");
    memoryRecords = r.records || [];
    renderMemory();
  } catch(e) { $("memory").textContent=e.message; }
}
function renderMemory(){
  const q = ($("memorySearch")?.value || "").trim().toLowerCase();
  const status = $("memoryStatusFilter")?.value || "";
  const filtered = memoryRecords.filter(m => {
    const hay = [m.content, m.fact_key, m.status, m.source_type, m.trust_tier, m.id].join(" ").toLowerCase();
    return (!q || hay.includes(q)) && (!status || m.status === status);
  });
  $("memory").innerHTML = filtered.length ? "" : "<div class='muted'>No matching memory.</div>";
  const groups = [
    ["Active trusted memory", "active"],
    ["Needs review / quarantined", "quarantined"],
    ["Replaced old facts", "superseded"],
    ["Forgotten / purged", "tombstoned"],
    ["Other", ""],
  ];
  for (const [label, groupStatus] of groups) {
    const records = filtered.filter(m => groupStatus ? m.status === groupStatus : !["active","quarantined","superseded","tombstoned"].includes(m.status));
    if (!records.length) continue;
    const group = document.createElement("div"); group.className = "group";
    group.innerHTML = `<div class="group-head"><span>${label}</span><span class="count">${records.length}</span></div>`;
    const byTopic = {};
    for (const record of records) {
      const topic = topicName(record);
      (byTopic[topic] ||= []).push(record);
    }
    for (const topic of Object.keys(byTopic).sort()) {
      const topicEl = document.createElement("div"); topicEl.className = "topic";
      topicEl.innerHTML = `<div class="topic-title">${escapeHtml(topic)}</div>`;
      for (const m of byTopic[topic].sort((a,b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))) {
        topicEl.appendChild(memoryCard(m));
      }
      group.appendChild(topicEl);
    }
    $("memory").appendChild(group);
  }
}
function topicName(m){
  const key = m.fact_key || m.scope || "general";
  return String(key).replace(/_/g, " ");
}
function memoryCard(m){
  const div=document.createElement("div"); div.className="card";
  const content = m.content || "(content purged)";
  const confidence = m.confidence == null ? "" : `<span>confidence ${Number(m.confidence).toFixed(2)}</span>`;
  div.innerHTML = `
    <div class="card-title">${escapeHtml(content)}</div>
    <div class="meta">
      <span>${escapeHtml(m.status || "")}</span>
      <span>${escapeHtml(m.source_type || "")}</span>
      <span>${escapeHtml(m.trust_tier || "")}</span>
      ${confidence}
      <span>${escapeHtml(m.id || "")}</span>
    </div>
    <details><summary>Details</summary><pre>${escapeHtml(JSON.stringify(m, null, 2))}</pre></details>
  `;
  return div;
}
async function refreshAudit(){
  try {
    const r = await api("/audit?subject="+encodeURIComponent(subject));
    const log = r.audit_log || [];
    $("audit").innerHTML = log.length ? "" : "<div class='muted'>No audit events yet.</div>";
    for (const e of log.slice().reverse().slice(0, 30)) {
      const div=document.createElement("div"); div.className="card";
      div.innerHTML = `<div class="card-title">${escapeHtml(e.event_type)}</div><div class="meta"><span>seq ${e.sequence}</span><span>${escapeHtml(e.actor || "")}</span><span>${escapeHtml(e.created_at || "")}</span></div><pre>${escapeHtml(JSON.stringify(e.payload || {}, null, 2))}</pre>`;
      $("audit").appendChild(div);
    }
  } catch(e) { $("audit").textContent=e.message; }
}
async function refreshVerify(){
  try {
    const r = await api("/verify?subject="+encodeURIComponent(subject));
    $("verifyStatus").innerHTML = `<span class="${r.audit_chain_valid?'ok':'bad'}">Audit chain valid: ${r.audit_chain_valid ? 'yes' : 'no'}</span>`;
  } catch(e) { $("verifyStatus").textContent=e.message; }
}
function escapeHtml(value){ return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
async function refreshProvider(){ try { const p=await api("/provider"); $("providerKind").value=p.kind; $("providerModel").value=p.model; $("providerBase").value=p.base_url||""; $("providerStatus").textContent=`${p.kind} / ${p.model}${p.base_url ? ' / '+p.base_url : ''} / key ${p.api_key_configured?'set':'not needed'}`; } catch(e){} }
async function refreshAll(){ await loadChecks(); await refreshProvider(); await refreshActions(); await refreshMemory(); await refreshAudit(); await refreshVerify(); }
loadTokens(); refreshAll();
</script>
</body>
</html>"""
