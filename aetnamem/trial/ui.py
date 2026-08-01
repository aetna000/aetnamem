"""Functional two-state dashboard for OpenClaw memory takeover.

The dashboard has no external assets or JavaScript dependencies. It presents
only the customer decisions that matter: inspect/search the mirror, activate
AetnaMem, or restore OpenClaw.
"""

APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AetnaMem for OpenClaw</title>
<style>
:root{
  --bg:#f4f6f5;--card:#fff;--ink:#172427;--muted:#627174;--line:#dce3e1;
  --brand:#087f68;--brand-soft:#e3f2ee;--blue:#2563eb;--blue-soft:#e8efff;
  --good:#18794e;--good-soft:#e4f2e9;--warn:#9a5b00;--warn-soft:#f7eddc;
  --bad:#b42318;--bad-soft:#fce8e6;--shadow:0 1px 2px #0e1f1b0a,0 10px 30px #0e1f1b0c
}
@media(prefers-color-scheme:dark){:root{
  --bg:#0e1514;--card:#16201e;--ink:#e8efed;--muted:#91a19d;--line:#2a3935;
  --brand:#2bb99b;--brand-soft:#12332c;--blue:#80a7ff;--blue-soft:#17274b;
  --good:#54c98b;--good-soft:#153525;--warn:#e0a54c;--warn-soft:#382812;
  --bad:#ff8178;--bad-soft:#3b1916;--shadow:0 1px 2px #0005,0 10px 30px #0004
}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
button,input{font:inherit}button{cursor:pointer}.mono{font-family:ui-monospace,"SFMono-Regular",
Consolas,monospace;font-variant-numeric:tabular-nums}.wrap{max-width:1080px;margin:0 auto;padding:0 24px}
header{height:64px;background:var(--card);border-bottom:1px solid var(--line);display:flex;align-items:center}
.head{display:flex;align-items:center;gap:12px;width:100%}.logo{font-size:18px;font-weight:800;letter-spacing:-.02em}
.logo span{color:var(--brand)}.grow{flex:1}.small{font-size:12px;color:var(--muted)}
.state{display:inline-flex;align-items:center;gap:7px;border-radius:99px;padding:6px 11px;
font-size:12px;font-weight:750;background:var(--blue-soft);color:var(--blue)}
.state:before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor}
.state.active{background:var(--good-soft);color:var(--good)}
main{padding:30px 0 60px}.hero,.card{background:var(--card);border:1px solid var(--line);
border-radius:14px;box-shadow:var(--shadow)}.hero{padding:26px 28px;margin-bottom:18px;
display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;align-items:center}
.eyebrow{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:800}
h1{font-size:28px;line-height:1.15;letter-spacing:-.035em;margin:5px 0 8px}
.hero p{color:var(--muted);margin:0;max-width:66ch}.actions{display:flex;gap:9px;align-items:center}
.primary,.secondary{border-radius:9px;padding:10px 15px;font-weight:750;white-space:nowrap}
.primary{background:var(--brand);border:1px solid var(--brand);color:#fff}.primary:hover{filter:brightness(.95)}
.primary:disabled{opacity:.45;cursor:not-allowed}.secondary{background:var(--card);
border:1px solid var(--line);color:var(--ink)}.secondary:hover{background:var(--bg)}
.grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,.8fr);gap:18px}
.card{padding:20px;margin-bottom:18px}.card h2{font-size:17px;margin:0 0 3px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px;margin:0 0 16px}.metrics{display:grid;
grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}.metric{background:var(--card);
border:1px solid var(--line);border-radius:11px;padding:13px 14px}.metric b{display:block;
font-size:21px;line-height:1.2}.metric span{font-size:11px;color:var(--muted)}
.search{display:flex;gap:8px}.search input{flex:1;min-width:0;border:1px solid var(--line);
border-radius:9px;background:var(--bg);color:var(--ink);padding:10px 12px}
.results{margin-top:14px}.result{border-top:1px solid var(--line);padding:13px 2px}
.result:first-child{border-top:0}.result p{margin:0 0 6px;white-space:pre-wrap}.meta{font-size:11px;
color:var(--muted);display:flex;gap:8px;flex-wrap:wrap}.pill{background:var(--brand-soft);
color:var(--brand);border-radius:99px;padding:2px 7px}.recordlink{border:0;background:none;color:var(--blue);
padding:0;text-decoration:underline;text-underline-offset:3px;font:inherit}.empty{color:var(--muted);padding:16px 2px}
.source{border-top:1px solid var(--line);padding:12px 2px}.source:first-child{border-top:0}
.sourcehead{display:flex;gap:10px;align-items:baseline}.sourcehead b{overflow-wrap:anywhere}
.plane{margin-left:auto;border-radius:99px;background:var(--blue-soft);color:var(--blue);
font-size:10px;font-weight:800;padding:2px 7px;text-transform:uppercase}.digest{font-size:10px;
color:var(--muted);overflow-wrap:anywhere;margin-top:4px}.check{display:flex;align-items:center;
gap:9px;padding:9px 0;border-top:1px solid var(--line)}.check:first-child{border-top:0}
.check i{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;
background:var(--good-soft);color:var(--good);font-style:normal;font-weight:900}.check.pending i{
background:var(--warn-soft);color:var(--warn)}.check span{font-size:12px;color:var(--muted)}
.notice{display:none;border:1px solid var(--bad);background:var(--bad-soft);color:var(--bad);
border-radius:10px;padding:11px 13px;margin-bottom:16px}.notice.show{display:block}
.progressbox{display:none;background:var(--card);border:1px solid var(--brand);
border-radius:12px;padding:15px 17px;margin-bottom:16px;box-shadow:var(--shadow)}
.progressbox.show{display:block}.progresshead{display:flex;justify-content:space-between;
gap:16px;margin-bottom:8px}.progresshead b{font-size:14px}.progresshead span{font-size:12px;
color:var(--muted)}.progressbar{height:8px;border-radius:99px;background:var(--brand-soft);
overflow:hidden}.progressbar span{display:block;width:38%;height:100%;border-radius:99px;
background:var(--brand);animation:working 1.15s ease-in-out infinite}
@keyframes working{0%{transform:translateX(-110%)}100%{transform:translateX(365%)}}
@media(prefers-reduced-motion:reduce){.progressbar span{animation-duration:2.5s}}
.foot{font-size:11px;color:var(--muted);margin-top:4px}.loading{opacity:.55;pointer-events:none}
button:focus-visible,input:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.backdrop{display:none;position:fixed;inset:0;background:#07110f99;z-index:20}.backdrop.show{display:block}
.drawer{position:absolute;right:0;top:0;min-height:100%;width:min(720px,94vw);background:var(--bg);
box-shadow:-20px 0 60px #0004;padding:22px;overflow:auto}.drawerhead{display:flex;gap:14px;align-items:start;
position:sticky;top:-22px;background:var(--bg);padding:20px 0 14px;z-index:2}.drawerhead h2{font-size:22px;
margin:2px 0}.close{margin-left:auto;width:38px;height:38px;border-radius:9px;border:1px solid var(--line);
background:var(--card);color:var(--ink);font-size:21px}.evidencegrid{display:grid;grid-template-columns:repeat(2,1fr);
gap:9px}.evidence{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:11px;
min-width:0}.evidence span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;
letter-spacing:.06em}.evidence b{display:block;margin-top:3px;overflow-wrap:anywhere}.chain{display:flex;gap:5px;
align-items:stretch;overflow:auto;padding:4px 0}.chainstep{min-width:104px;flex:1;border:1px solid var(--line);
border-radius:9px;padding:9px;background:var(--card);font-size:11px}.chainstep b{display:block;font-size:12px}
.chainstep.ok{border-color:var(--good);background:var(--good-soft)}.chainstep.missing{color:var(--muted)}
.timeline{border-left:2px solid var(--line);margin-left:7px;padding-left:17px}.event{position:relative;
padding:0 0 17px}.event:before{content:"";position:absolute;left:-23px;top:5px;width:10px;height:10px;
border-radius:50%;background:var(--brand);border:2px solid var(--bg)}.event b{display:block}.event p{margin:2px 0;
color:var(--muted);font-size:12px}.downloads{display:flex;gap:8px;flex-wrap:wrap}.downloads a{display:inline-flex;
text-decoration:none}.delivery{border-top:1px solid var(--line);padding:11px 0}.delivery:first-child{border-top:0}
.delivery b{display:block}.integrity{color:var(--good);font-weight:800}.integrity.bad{color:var(--bad)}
@media(max-width:780px){.wrap{padding:0 14px}.hero{grid-template-columns:1fr;padding:20px}
.actions{width:100%}.actions button{flex:1}.grid{grid-template-columns:1fr}.metrics{
grid-template-columns:repeat(2,1fr)}header .small{display:none}.evidencegrid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><div class="wrap head">
  <div class="logo"><span>Aetna</span>Mem</div>
  <div class="small">OpenClaw memory</div>
  <div class="grow"></div>
  <div class="state" id="stateChip">Checking…</div>
</div></header>
<main class="wrap">
  <div class="notice" id="error" role="alert"></div>
  <div class="progressbox" id="progress" role="status" aria-live="polite">
    <div class="progresshead">
      <b id="progressTitle">Working…</b>
      <span class="mono" id="progressTime">0s</span>
    </div>
    <p class="sub" id="progressDetail">Please keep this page open.</p>
    <div class="progressbar" aria-hidden="true"><span></span></div>
  </div>
  <section class="hero" id="hero">
    <div>
      <div class="eyebrow" id="eyebrow">Memory provider</div>
      <h1 id="title">Checking your OpenClaw memory…</h1>
      <p id="summary">AetnaMem is verifying the mirrored copy and the rollback snapshot.</p>
    </div>
    <div class="actions">
      <button class="secondary" id="refreshBtn">Refresh mirror</button>
      <button class="primary" id="switchBtn" disabled>Activate AetnaMem</button>
    </div>
  </section>

  <div class="metrics">
    <div class="metric"><b class="mono" id="sourceCount">—</b><span>mirrored files</span></div>
    <div class="metric"><b class="mono" id="recordCount">—</b><span>searchable memories</span></div>
    <div class="metric"><b class="mono" id="sourceBytes">—</b><span>source bytes preserved</span></div>
    <div class="metric"><b id="verified">—</b><span>mirror verification</span></div>
  </div>

  <div class="grid">
    <div>
      <section class="card">
        <h2>Search memory</h2>
        <p class="sub">Search the AetnaMem copy using ordinary words. This works before and after switching.</p>
        <div class="search">
          <input id="query" placeholder="For example: TypeScript preference" autocomplete="off">
          <button class="primary" id="searchBtn">Search</button>
        </div>
        <div class="results" id="results"><div class="empty">Enter a question to inspect the mirrored memory.</div></div>
      </section>

      <section class="card">
        <h2>Exactly what is mirrored</h2>
        <p class="sub" id="sourceSummary">Loading the verified source manifest…</p>
        <div id="sources"><div class="empty">Loading sources…</div></div>
      </section>
    </div>

    <aside>
      <section class="card">
        <h2 id="switchTitle">Ready to switch?</h2>
        <p class="sub" id="switchCopy">AetnaMem checks every safety condition before changing OpenClaw.</p>
        <div id="checks"></div>
      </section>
      <section class="card">
        <h2>What changes</h2>
        <div class="check"><i>✓</i><div>OpenClaw keeps using <span class="mono">memory_search</span> and <span class="mono">memory_get</span>.</div></div>
        <div class="check"><i>✓</i><div>AetnaMem becomes the memory store and records searches and reads.</div></div>
        <div class="check"><i>✓</i><div>The original OpenClaw memory is frozen and can be restored.</div></div>
        <div class="check"><i>✓</i><div>Identity, tools, skills and transcripts stay with OpenClaw.</div></div>
      </section>
      <p class="foot mono" id="identity"></p>
    </aside>
  </div>
</main>
<div class="backdrop" id="auditorBackdrop" aria-hidden="true">
  <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="auditorTitle">
    <div class="drawerhead">
      <div><div class="eyebrow">Auditor record history</div><h2 id="auditorTitle">Loading evidence…</h2>
      <div class="mono small" id="auditorId"></div></div>
      <button class="close" id="auditorClose" aria-label="Close record history">×</button>
    </div>
    <div id="auditorBody"><div class="empty">Loading the verified audit chain…</div></div>
  </aside>
</div>
<script>
(function(){
"use strict";
var state=null,csrf="",progressTimer=null,progressStarted=0;
var $=function(id){return document.getElementById(id)};
function text(id,value){$(id).textContent=value==null?"—":String(value)}
function number(value){return Number(value||0).toLocaleString()}
function showError(error){text("error",error&&error.message?error.message:error);$("error").classList.add("show")}
function clearError(){$("error").classList.remove("show")}
function showProgress(title,detail){
 text("progressTitle",title);text("progressDetail",detail);progressStarted=Date.now();
 text("progressTime","0s");$("progress").classList.add("show");$("hero").classList.add("loading");
 $("switchBtn").disabled=true;$("refreshBtn").disabled=true;
 if(progressTimer)clearInterval(progressTimer);
 progressTimer=setInterval(function(){text("progressTime",Math.floor((Date.now()-progressStarted)/1000)+"s")},1000)
}
function hideProgress(){
 if(progressTimer)clearInterval(progressTimer);progressTimer=null;$("progress").classList.remove("show");
 $("hero").classList.remove("loading");$("refreshBtn").disabled=false;
 var readiness=state&&state.readiness?state.readiness:{};
 $("switchBtn").disabled=active()?false:!readiness.ready_for_active
}
async function working(title,detail,operation){
 clearError();showProgress(title,detail);
 try{return await operation()}finally{hideProgress()}
}
async function get(path){var r=await fetch(path,{headers:{"Accept":"application/json"}});var v=await r.json();if(!r.ok)throw new Error(v.error||"Request failed");return v}
async function post(path,body){var r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify(body||{})});var v=await r.json();if(!r.ok)throw new Error(v.error||"Request failed");return v}
function element(name,className,value){var node=document.createElement(name);if(className)node.className=className;if(value!=null)node.textContent=value;return node}
function active(){return !!(state&&state.takeover&&state.takeover.active)}
function recovery(){return !!(state&&state.takeover&&state.takeover.requires_restore)}
function shortDigest(value){return value?String(value).slice(0,16)+"…":"not recorded"}
function evidence(label,value,mono){var box=element("div","evidence"),name=element("span","",label),body=element("b",mono?"mono":"",value||"not recorded");box.append(name,body);return box}
function chainStep(label,ok,detail){var box=element("div","chainstep "+(ok?"ok":"missing"));box.append(element("b","",label),element("span","",detail));return box}
function closeAuditor(){$("auditorBackdrop").classList.remove("show");$("auditorBackdrop").setAttribute("aria-hidden","true")}
async function inspectRecord(recordId){
 clearError();$("auditorBackdrop").classList.add("show");$("auditorBackdrop").setAttribute("aria-hidden","false");
 text("auditorTitle","Loading evidence…");text("auditorId",recordId);$("auditorBody").replaceChildren(element("div","empty","Verifying the complete record history…"));
 try{
  var report=await get("/api/mirror/record?record_id="+encodeURIComponent(recordId)),record=report.record||{},p=report.provenance||{},life=report.lifecycle||{},deliveries=report.deliveries||[],timeline=report.timeline||[],body=$("auditorBody");body.replaceChildren();
  text("auditorTitle",record.content||"Purged memory record");
  var integrity=element("p","integrity"+(report.audit_chain_valid?"":" bad"),report.audit_chain_valid?"✓ Audit chain verified":"✕ Audit chain verification failed");body.appendChild(integrity);
  var chain=element("div","chain");var delivered=deliveries.some(function(d){return !!d.context_injected_at}),responded=deliveries.some(function(d){return !!d.response_sha256});
  chain.append(chainStep("Source",!!p.source_message_sha256,shortDigest(p.source_message_sha256)),chainStep("Interpret",!!p.interpreting_model,p.interpreting_model||"native import"),chainStep("Admit",!!life.created_at,life.created_at||"not recorded"),chainStep("Recall",deliveries.length>0,deliveries.length+" attempt"+(deliveries.length===1?"":"s")),chainStep("Inject",delivered,delivered?"context receipt":"not recorded"),chainStep("Respond",responded,responded?"digest bound":"not recorded"));
  var chainCard=element("section","card");chainCard.append(element("h2","","Evidence chain"),element("p","sub","Source → interpretation → admission → recall → context injection → agent response"),chain);body.appendChild(chainCard);
  var prov=element("section","card"),provGrid=element("div","evidencegrid");prov.append(element("h2","","Source and interpretation"),element("p","sub","Digests prove identity without exposing the original message."));
  provGrid.append(evidence("Source-message SHA-256",p.source_message_sha256,true),evidence("Interpreting model",p.interpreting_model||"Native OpenClaw import",false),evidence("Source binding",p.source_binding||p.interpretation_assurance,false),evidence("Native source",p.native_path||"Not a native-file import",true),evidence("Episode",p.episode_id,true),evidence("Memory plane",p.plane,false));prov.appendChild(provGrid);body.appendChild(prov);
  var lifecycle=element("section","card"),lifeGrid=element("div","evidencegrid");lifecycle.append(element("h2","","Record lifecycle"),element("p","sub","Canonical state changes preserved in chronological audit evidence."));lifeGrid.append(evidence("Status",report.status,false),evidence("Created",life.created_at,false),evidence("Superseded",life.superseded_at||"Not superseded",false),evidence("Deleted",life.deleted_at||"Not deleted",false));lifecycle.appendChild(lifeGrid);body.appendChild(lifecycle);
  var deliveryCard=element("section","card");deliveryCard.append(element("h2","","Recall and agent delivery"),element("p","sub","Every candidate score is distinct from proof that the memory entered context or influenced a response."));
  if(!deliveries.length)deliveryCard.appendChild(element("div","empty","This record has not appeared in a recorded recall."));
  deliveries.forEach(function(d){var item=element("div","delivery");item.append(element("b","","Rank "+d.rank+" · score "+d.score+(d.returned?" · returned":" · candidate only")),element("div","small mono",d.recalled_at+" · "+(d.session_id||"no session")),element("div","small","Context injection: "+(d.context_injected_at||"not recorded")),element("div","small mono","Agent response digest: "+(d.response_sha256||"not recorded")));deliveryCard.appendChild(item)});body.appendChild(deliveryCard);
  var timeCard=element("section","card"),timeBox=element("div","timeline");timeCard.append(element("h2","","Complete chronological history"),element("p","sub",timeline.length+" linked evidence event"+(timeline.length===1?"":"s")+"."));
  timeline.forEach(function(e){var item=element("div","event");item.append(element("b","",e.title||e.type),element("p","",e.detail||""),element("div","small mono",(e.at||"unknown time")+" · "+(e.event_id||"no evidence ID")+(e.session_id?" · "+e.session_id:"")));timeBox.appendChild(item)});if(!timeline.length)timeBox.appendChild(element("div","empty","No linked events were retained."));timeCard.appendChild(timeBox);body.appendChild(timeCard);
  var downloads=element("section","card"),links=element("div","downloads");downloads.append(element("h2","","Export evidence"),element("p","sub","Download a portable investigation report. A deletion receipt appears only after a verified purge."));
  [["JSON report","json"],["Text report","text"]].forEach(function(pair){var a=element("a","secondary",pair[0]);a.href="/api/mirror/record-report?record_id="+encodeURIComponent(recordId)+"&format="+pair[1];links.appendChild(a)});
  if(report.deletion_receipt){var receipt=element("a","secondary","Deletion receipt");receipt.href="/api/mirror/deletion-receipt?record_id="+encodeURIComponent(recordId);links.appendChild(receipt)}downloads.appendChild(links);body.appendChild(downloads)
 }catch(error){$("auditorBody").replaceChildren(element("div","notice show",error.message||String(error)))}
}
function renderSources(mirror){
 var box=$("sources");box.replaceChildren();var rows=Array.isArray(mirror.sources)?mirror.sources:[];
 if(!rows.length){box.appendChild(element("div","empty","No mirrored source files were found."));return}
 rows.forEach(function(row){
  var item=element("div","source"),head=element("div","sourcehead"),name=element("b","",row.relative_path||"unknown");
  var bytes=element("span","small mono",number(row.bytes)+" bytes"),plane=element("span","plane",row.plane||"memory");
  head.append(name,bytes,plane);item.append(head);
  item.appendChild(element("div","digest mono","SHA-256  "+(row.sha256||"not recorded")));
  box.appendChild(item)
 });
 text("sourceSummary",rows.length+" verified source file"+(rows.length===1?"":"s")+" from "+(mirror.workspace||"the OpenClaw workspace")+".")
}
function addCheck(label,ok,detail){
 var row=element("div","check"+(ok?"":" pending")),icon=element("i","",ok?"✓":"!"),body=element("div","",label);
 if(detail)body.appendChild(element("span","", " — "+detail));row.append(icon,body);$("checks").appendChild(row)
}
function render(){
 if(!state)return;var mirror=state.mirror||{},takeover=state.takeover||{},isActive=active(),needsRecovery=recovery(),readiness=state.readiness||{};
 $("stateChip").className="state"+(isActive?" active":"");
 text("stateChip",isActive?"AetnaMem active":needsRecovery?"Restore required":"OpenClaw active");
 text("eyebrow",isActive?"Current memory provider":needsRecovery?"Interrupted switch detected":"Safe side-by-side copy");
 text("title",isActive?"AetnaMem is managing OpenClaw memory":needsRecovery?"Restore OpenClaw before activating":"OpenClaw memory is still active");
 text("summary",isActive
  ?"AetnaMem now serves bounded, governed memory. Your original OpenClaw memory is preserved for restoration."
  :needsRecovery
  ?(takeover.recovery_message||"AetnaMem preserved the switch evidence and must verify restoration before another activation.")
  :"AetnaMem mirrors and verifies your existing memory without changing what OpenClaw uses.");
 text("sourceCount",mirror.source_count);text("recordCount",mirror.record_count);text("sourceBytes",number(mirror.source_bytes));
 text("verified",mirror.audit_verified?"PASSED":"CHECK");
 text("switchBtn",isActive||needsRecovery?"Restore OpenClaw":"Activate AetnaMem");
 $("refreshBtn").style.display=isActive||needsRecovery?"none":"inline-block";
 $("switchBtn").disabled=isActive||needsRecovery?false:!readiness.ready_for_active;
 text("switchTitle",isActive||needsRecovery?"Restore OpenClaw":"Ready to activate?");
 text("switchCopy",isActive||needsRecovery
  ?"Restore the verified native files and make OpenClaw memory authoritative again."
  :"One switch freezes the current native state, verifies the AetnaMem runtime, and rolls back automatically if anything fails.");
 text("identity",(state.host||"openclaw")+" · "+(state.subject_id||"local-user")+" · "+(state.trial_id||""));
 renderSources(mirror);$("checks").replaceChildren();
 if(isActive){
  addCheck("Native memory snapshot",!!takeover.native_snapshot_verified,"verified");
  addCheck("OpenClaw gateway",!!takeover.gateway_verified,"running");
  addCheck("Memory tools",!!takeover.compatibility_tools_verified,"memory_search and memory_get");
  addCheck("Capture hooks",!!takeover.capture_hooks_verified,"verified");
 }else if(needsRecovery){
  addCheck("Interrupted switch",false,"status: "+(takeover.status||"unknown"));
  addCheck("Recovery action",false,"Restore OpenClaw verifies the preserved files");
 }else{
  addCheck("Mirror synchronized",!!mirror.synced,number(mirror.source_count)+" sources");
  addCheck("Mirror audit",!!mirror.audit_verified,mirror.audit_error||"verified");
  addCheck("Searchable records",number(mirror.record_count)>0,number(mirror.record_count)+" ready");
  addCheck("Safe activation",!!readiness.ready_for_active,(readiness.reasons||[])[0]||"ready");
 }
}
async function reload(){state=await get("/api/status");render()}
async function search(){
 var query=$("query").value.trim();if(!query)return;clearError();$("results").replaceChildren(element("div","empty","Searching…"));
 try{
  var value=await get("/api/mirror/search?query="+encodeURIComponent(query)),rows=value.records||[],box=$("results");box.replaceChildren();
  if(!rows.length){box.appendChild(element("div","empty","No matching memory found."));return}
  rows.forEach(function(row){
   var p=row.openclaw_provenance||{},item=element("div","result"),body=element("p","",row.match_excerpt||row.content||"");
   var meta=element("div","meta");meta.append(element("span","pill",p.plane||row.scope||"memory"));
   if(row.id){var recordButton=element("button","recordlink mono",row.id);recordButton.type="button";recordButton.onclick=function(){inspectRecord(row.id)};meta.append(recordButton)}
   else meta.append(element("span","mono",p.relative_path||""));
   if(p.relative_path)meta.append(element("span","mono",p.relative_path));
   if(p.line_start)meta.append(element("span","mono","lines "+p.line_start+"–"+(p.line_end||p.line_start)));
   item.append(body,meta);box.appendChild(item)
  })
 }catch(error){showError(error)}
}
async function refresh(){
 try{await working("Refreshing the memory mirror","Reading native files, rebuilding the search index, and verifying its audit evidence.",async function(){await post("/api/mirror/sync",{});await reload()})}
 catch(error){showError(error)}
}
async function switchProvider(){
 if(!state)return;clearError();
 if(active()||recovery()){
  if(!confirm("Restore the verified OpenClaw memory and stop AetnaMem memory takeover?"))return;
  try{await working("Restoring OpenClaw memory","Restoring and verifying the frozen native files, then restarting OpenClaw. This can take a minute.",async function(){await post("/api/rollback",{});await reload()})}
  catch(error){showError(error)}
  return
 }
 var expected=state.host||"openclaw";
 var entered=prompt("To activate AetnaMem, type '"+expected+"':");
 if(entered===null)return;
 try{await working("Activating AetnaMem","Freezing native memory, checking compatibility, restarting OpenClaw, and verifying memory tools. This can take a minute.",async function(){await post("/api/mode",{mode:"active",confirm_host:entered});await reload()})}
 catch(error){showError(error)}
}
$("searchBtn").onclick=search;$("query").addEventListener("keydown",function(event){if(event.key==="Enter")search()});
$("refreshBtn").onclick=refresh;$("switchBtn").onclick=switchProvider;
$("auditorClose").onclick=closeAuditor;$("auditorBackdrop").addEventListener("click",function(event){if(event.target===$("auditorBackdrop"))closeAuditor()});document.addEventListener("keydown",function(event){if(event.key==="Escape")closeAuditor()});
async function init(){try{csrf=(await get("/api/session")).csrf_token;await reload()}catch(error){showError(error)}}
init()
})();
</script>
</body>
</html>
"""
