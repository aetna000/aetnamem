"""Self-contained Safe Switch dashboard.

The dashboard intentionally has no external assets or JavaScript dependencies.
All values are loaded from the loopback-only, authenticated trial API.
"""

APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AetnaMem Safe Switch</title>
<style>
:root{
  --paper:#f7f8f7;--raised:#fff;--ink:#1a2b2f;--muted:#5b6e72;
  --line:#dde4e2;--accent:#008a70;--accent-soft:#e3f1ee;
  --violet:#8256e8;--good:#1b7f4d;--good-soft:#e3f0e8;
  --warn:#9a5b00;--warn-soft:#f5ebdb;--bad:#b3261e;--bad-soft:#f6e4e2;
  --neutral:#eaedec;--shadow:0 1px 2px #1a2b2f0f,0 8px 24px #1a2b2f12
}
@media(prefers-color-scheme:dark){:root{
  --paper:#0f1715;--raised:#16211f;--ink:#e4ecea;--muted:#8ca09b;
  --line:#263531;--accent:#0ea88c;--accent-soft:#12312b;
  --violet:#8e75e8;--good:#3fae72;--good-soft:#14301f;
  --warn:#d99a3d;--warn-soft:#33270f;--bad:#e5716a;--bad-soft:#391513;
  --neutral:#1e2a27;--shadow:0 1px 2px #0006,0 8px 24px #0005
}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:13px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
button,input{font:inherit}button{cursor:pointer}.mono{font-family:ui-monospace,"SFMono-Regular",
Consolas,monospace;font-variant-numeric:tabular-nums}
button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.top{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:10px;
padding:10px 16px;background:var(--raised);border-bottom:1px solid var(--line)}
.brand{font-weight:750;font-size:15px}.brand small{font-weight:500;color:var(--muted);margin-left:6px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:99px;
font-size:12px;font-weight:650;background:var(--neutral);color:var(--muted)}
.chip i{width:7px;height:7px;border-radius:50%;background:currentColor}.chip.capture,.chip.preview{
background:var(--accent-soft);color:var(--accent)}.chip.canary{background:var(--warn-soft);
color:var(--warn)}.chip.active{background:var(--good-soft);color:var(--good)}
.grow{flex:1}.danger{border:1px solid var(--bad);color:var(--bad);background:transparent;
border-radius:8px;padding:6px 12px;font-weight:650}.danger:hover{background:var(--bad-soft)}
.shell{display:grid;grid-template-columns:214px minmax(0,1fr);min-height:calc(100vh - 49px)}
.rail{border-right:1px solid var(--line);padding:16px 0;display:flex;flex-direction:column}
.nav{display:flex;align-items:center;gap:10px;width:100%;border:0;border-left:3px solid
transparent;background:none;color:var(--muted);padding:10px 18px;text-align:left}
.nav[aria-current=true]{color:var(--ink);font-weight:700;border-left-color:var(--accent);
background:var(--accent-soft)}.nd{width:8px;height:8px;border-radius:50%;background:var(--line)}
.nd.data{background:var(--accent)}.nd.pass{background:var(--good)}.nd.warn{background:var(--warn)}
.railfoot{margin-top:auto;padding:14px 18px;border-top:1px solid var(--line);
font-size:11px;color:var(--muted);overflow-wrap:anywhere}
main{padding:22px 26px 60px;max-width:1040px;width:100%}section[hidden]{display:none}
h1{font-size:21px;letter-spacing:-.02em;margin:0 0 4px}.sub{color:var(--muted);
margin:0 0 18px;max-width:68ch}.banner{border:1px solid var(--accent);
background:var(--accent-soft);border-radius:10px;padding:16px 20px;margin-bottom:18px}
.banner h1{color:var(--accent);font-size:17px;letter-spacing:.02em}.banner p{margin:5px 0 0}
.banner.canary{border-color:var(--warn);background:var(--warn-soft)}.banner.canary h1{color:var(--warn)}
.banner.active{border-color:var(--good);background:var(--good-soft)}.banner.active h1{color:var(--good)}
.banner.off{border-color:var(--line);background:var(--neutral)}.banner.off h1{color:var(--muted)}
.tiles{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:12px;margin-bottom:18px}
.tile,.card{background:var(--raised);border:1px solid var(--line);border-radius:10px;
box-shadow:var(--shadow)}.tile{padding:12px 14px}.tile .v{font-size:24px;font-weight:700}
.tile .d,.why{color:var(--muted);font-size:12px}.card{padding:16px 18px;margin-bottom:16px}
.label{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}
.notdoing{padding:0;margin:8px 0 0;list-style:none}.notdoing li{padding:5px 0 5px 24px;
position:relative;color:var(--muted)}.notdoing li:before{content:"✕";position:absolute;left:4px;
color:var(--good);font-weight:800}.primary,.ghost{border-radius:8px;padding:7px 13px;font-weight:700}
.primary{border:1px solid var(--accent);background:var(--accent);color:white}.primary:disabled{
opacity:.45;cursor:not-allowed}.ghost{border:1px solid var(--line);background:var(--raised);color:var(--ink)}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.filter{border:1px solid var(--line);
background:var(--raised);border-radius:99px;padding:4px 12px;color:var(--muted)}
.filter[aria-pressed=true]{border-color:var(--accent);background:var(--accent-soft);
color:var(--accent);font-weight:700}.mem{padding:12px 2px;border-bottom:1px solid var(--line)}
.mem:last-child{border:0}.memrow{display:flex;gap:10px;align-items:flex-start}.memtext{flex:1;min-width:0}
.status{font-size:10.5px;font-weight:750;letter-spacing:.05em;text-transform:uppercase;
padding:2px 8px;border-radius:5px}.status.candidate{background:var(--warn-soft);color:var(--warn)}
.status.approved{background:var(--good-soft);color:var(--good)}.status.rejected{
background:var(--neutral);color:var(--muted)}.acts{display:flex;gap:6px}.acts button{
border:1px solid var(--line);background:var(--raised);color:var(--ink);border-radius:7px;padding:4px 10px}
.acts .ok{border-color:var(--good);color:var(--good)}.empty{text-align:center;color:var(--muted);
padding:30px 12px}.note{border:1px solid var(--accent);background:var(--accent-soft);
color:var(--accent);border-radius:8px;padding:9px 13px;margin-bottom:16px;font-weight:650}
.gate{display:flex;gap:10px;align-items:baseline;padding:7px 0;border-bottom:1px solid var(--line)}
.gate:last-child{border:0}.gate .m{margin-left:auto;color:var(--muted);text-align:right}
.g{min-width:46px;text-align:center;font-size:10px;font-weight:800;padding:2px 6px;border-radius:5px}
.g.pass{background:var(--good-soft);color:var(--good)}.g.pend{background:var(--warn-soft);color:var(--warn)}
.chart{width:100%;height:auto;min-height:190px}.chart text{fill:var(--muted);font-size:11px}
.chart .grid{stroke:var(--line);stroke-width:1}.chart .bar{fill:var(--accent)}
.chart .bar2{fill:var(--violet)}.chartvalue{fill:var(--ink)!important;font-family:ui-monospace,monospace}
.legend{display:flex;gap:16px;color:var(--muted);font-size:12px;margin:8px 0}.legend i{
display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;background:var(--accent)}
.stage{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center}.error{
display:none;background:var(--bad-soft);color:var(--bad);border:1px solid var(--bad);
padding:9px 12px;border-radius:8px;margin-bottom:14px}.error.show{display:block}
.skeleton{opacity:.55}.hash{overflow-wrap:anywhere}
@media(max-width:760px){.shell{grid-template-columns:1fr}.rail{position:sticky;top:49px;z-index:4;
flex-direction:row;overflow:auto;padding:0;background:var(--paper);border-right:0;border-bottom:1px solid var(--line)}
.nav{white-space:nowrap;border-left:0;border-bottom:3px solid transparent}.nav[aria-current=true]{
border-bottom-color:var(--accent)}.railfoot{display:none}main{padding:16px}.tiles{grid-template-columns:repeat(2,1fr)}
.top .optional{display:none}.memrow{flex-wrap:wrap}.acts{width:100%}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
</head>
<body>
<header class="top">
  <span class="brand">AetnaMem <small>Safe Switch</small></span>
  <span class="chip" id="modeChip"><i></i><span id="modeText">LOADING</span></span>
  <span class="chip optional" id="hostChip">host</span>
  <span class="chip optional" id="subjectChip">subject</span>
  <span class="grow"></span>
  <button class="danger" id="offBtn">Emergency off</button>
</header>
<div class="shell">
  <nav class="rail" aria-label="Trial sections">
    <button class="nav" data-section="overview" aria-current="true"><span class="nd data"></span>Overview</button>
    <button class="nav" data-section="memory"><span class="nd warn"></span>Memory</button>
    <button class="nav" data-section="preview"><span class="nd"></span>Recall Preview</button>
    <button class="nav" data-section="comparison"><span class="nd"></span>Evidence</button>
    <button class="nav" data-section="switch"><span class="nd"></span>Switch</button>
    <button class="nav" data-section="value"><span class="nd"></span>Value</button>
    <div class="railfoot mono"><span id="trialId">loading</span><br><span id="version">AetnaMem 0.6.1.1a1 experimental</span></div>
  </nav>
  <main>
    <div class="error" id="error" role="alert"></div>
    <section id="section-overview">
      <div class="banner" id="banner" role="status">
        <h1 id="bannerTitle">LOADING LOCAL TRIAL EVIDENCE</h1><p id="bannerBody"></p>
      </div>
      <div class="tiles">
        <div class="tile"><div class="v mono" id="turns">—</div><div class="d">turns observed</div></div>
        <div class="tile"><div class="v mono" id="candidateCount">—</div><div class="d">memory candidates</div></div>
        <div class="tile"><div class="v mono" id="previewCount">—</div><div class="d">recall previews</div></div>
        <div class="tile"><div class="v mono">$0.00</div><div class="d">extra provider spend</div></div>
      </div>
      <div class="card">
        <span class="label">What AetnaMem is not doing right now</span>
        <ul class="notdoing" id="notDoing"></ul>
      </div>
      <div class="card stage">
        <div><span class="label">Suggested next step</span><p id="nextText"></p></div>
        <button class="primary" id="nextBtn">Continue</button>
      </div>
    </section>

    <section id="section-memory" hidden>
      <h1>Memory</h1>
      <p class="sub">Captured memory candidates with their source and review state. Capture and preview modes do not show these to your agent.</p>
      <div class="filters" id="filters"></div>
      <div class="card" id="memoryList"><div class="empty">Loading memory candidates…</div></div>
    </section>

    <section id="section-preview" hidden>
      <h1>Recall Preview</h1>
      <p class="sub">What AetnaMem has computed after observed turns.</p>
      <div class="note">◎ Previews are computed after the fact in preview mode. They are shown to the agent only in canary or active mode.</div>
      <div class="tiles">
        <div class="tile"><div class="v mono" id="previews2">—</div><div class="d">previews computed</div></div>
        <div class="tile"><div class="v mono" id="exposures">—</div><div class="d">contexts requested</div></div>
        <div class="tile"><div class="v mono" id="shown">—</div><div class="d">contexts confirmed shown</div></div>
        <div class="tile"><div class="v mono" id="withheld">—</div><div class="d">previews not exposed</div></div>
      </div>
      <div class="card"><span class="label">Privacy boundary</span>
        <p id="previewExplanation">Queries are stored as digests; the dashboard reports aggregate evidence without inventing the original prompt text.</p>
      </div>
    </section>

    <section id="section-comparison" hidden>
      <h1>Evidence</h1>
      <p class="sub">A live view of the trial funnel. This is operational evidence, not a claim that AetnaMem improved success or cost.</p>
      <div class="card">
        <span class="label">Observed trial funnel</span>
        <div class="legend"><span><i></i>Recorded local evidence</span></div>
        <svg class="chart" viewBox="0 0 720 230" role="img" aria-label="Trial evidence counts">
          <g class="grid"><line x1="54" y1="190" x2="700" y2="190"/><line x1="54" y1="120" x2="700" y2="120"/><line x1="54" y1="50" x2="700" y2="50"/></g>
          <g id="funnelBars"></g>
        </svg>
      </div>
      <div class="card"><span class="label">Quantitative comparison</span>
        <p><b>Not measured in this trial yet.</b></p>
        <p class="why">The 0.6.1.1a1 experimental dashboard will not turn preview counts into a performance claim. Paid paired comparison and host-verified outcomes remain a later beta milestone.</p>
      </div>
    </section>

    <section id="section-switch" hidden>
      <h1>Switch</h1>
      <p class="sub">Progressive exposure. The server re-checks every readiness gate; the browser cannot override a failed gate.</p>
      <div class="card"><span class="label">Readiness gates</span><div id="gates"></div></div>
      <div class="card stage"><div><b>Preview only</b><p class="why">Compute recalls after the fact. Your agent still receives no AetnaMem context.</p></div>
        <button class="primary" id="previewBtn">Enter preview</button></div>
      <div class="card stage"><div><b>Limited canary</b><p class="why">Serve memory for a bounded number of eligible turns, then stop injecting.</p></div>
        <button class="primary" id="canaryBtn">Start 20-turn canary</button></div>
      <div class="card stage"><div><b>Activate</b><p class="why">Available only after the configured canary exposures are confirmed healthy.</p></div>
        <button class="primary" id="activeBtn">Make active</button></div>
    </section>

    <section id="section-value" hidden>
      <h1>Value</h1>
      <p class="sub">What AetnaMem can prove from this local trial today.</p>
      <div class="tiles">
        <div class="tile"><div class="v mono" id="served">—</div><div class="d">confirmed contexts served</div></div>
        <div class="tile"><div class="v mono" id="approved">—</div><div class="d">memories approved by you</div></div>
        <div class="tile"><div class="v mono" id="chainEvents">—</div><div class="d">mode events in audit chain</div></div>
        <div class="tile"><div class="v mono" id="chainState">—</div><div class="d">audit chain status</div></div>
      </div>
      <div class="card"><span class="label">Claims boundary</span>
        <p id="valueClaim"><b>No performance claim yet.</b> Capture proves observation, preview proves proposed recall, and shown exposure proves context delivery. Success and savings require a verified comparison.</p>
      </div>
    </section>
  </main>
</div>
<script>
(function(){
"use strict";
var state=null,candidates=[],csrf="",filter="all";
var $=function(id){return document.getElementById(id)};
function escText(node,value){node.textContent=value==null?"—":String(value)}
function short(value){value=String(value||"");return value.length>18?value.slice(0,8)+"…"+value.slice(-6):value}
function num(value){return Number(value||0)}
function showError(error){var box=$("error");box.textContent=error&&error.message?error.message:String(error);box.classList.add("show")}
function clearError(){$("error").classList.remove("show")}
async function get(path){var r=await fetch(path,{headers:{"Accept":"application/json"}});var v=await r.json();if(!r.ok)throw new Error(v.error||"Request failed");return v}
async function post(path,body){var r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify(body)});var v=await r.json();if(!r.ok)throw new Error(v.error||"Request failed");return v}
function show(section){
 document.querySelectorAll("main section").forEach(function(s){s.hidden=s.id!=="section-"+section});
 document.querySelectorAll(".nav").forEach(function(b){b.setAttribute("aria-current",b.dataset.section===section?"true":"false")})
}
document.querySelectorAll(".nav").forEach(function(b){b.addEventListener("click",function(){show(b.dataset.section)})});
function counts(){var c=(state&&state.evidence&&state.evidence.candidates)||{};return{candidate:num(c.candidate),approved:num(c.approved),rejected:num(c.rejected)}}
function modeCopy(mode){
 var all={
  off:["OFF — AETNAMEM IS NOT RUNNING","No capture and no context influence. Your host keeps running normally."],
  capture:["OBSERVING — NOT INFLUENCING YOUR AGENT","AetnaMem is collecting quarantined candidates locally. Your current memory and provider remain in control."],
  preview:["PREVIEWING — NOTHING SHOWN TO THE AGENT","AetnaMem computes what it would recall after the fact. The agent prompt remains untouched."],
  canary:["CANARY — LIMITED CONTEXT EXPOSURE","AetnaMem may serve bounded memory context for the configured canary turns. Emergency off remains available."],
  active:["ACTIVE — AETNAMEM IS SERVING MEMORY","AetnaMem is serving governed context. The local evidence chain records mode changes and exposures."]
 };return all[mode]||all.off
}
function render(){
 if(!state)return;var ev=state.evidence||{candidates:{},turns:0,previews:0,exposures:0,shown_exposures:0,shown_canary_exposures:0,transition_chain:{valid:false,events:0}};
 var c=counts(),total=c.candidate+c.approved+c.rejected,mode=state.mode||"off",copy=modeCopy(mode);
 $("modeChip").className="chip "+mode;escText($("modeText"),mode.toUpperCase());escText($("hostChip"),state.host||"unknown host");
 escText($("subjectChip"),"subject: "+(state.subject_id||"unknown"));escText($("trialId"),short(state.trial_id));$("banner").className="banner "+mode;
 escText($("bannerTitle"),copy[0]);escText($("bannerBody"),copy[1]);$("offBtn").style.visibility=mode==="off"?"hidden":"visible";
 escText($("turns"),ev.turns);escText($("candidateCount"),total);escText($("previewCount"),ev.previews);
 escText($("previews2"),ev.previews);escText($("exposures"),ev.exposures);escText($("shown"),ev.shown_exposures);
 escText($("withheld"),Math.max(0,num(ev.previews)-num(ev.exposures)));escText($("served"),ev.shown_exposures);
 escText($("approved"),c.approved);escText($("chainEvents"),ev.transition_chain&&ev.transition_chain.events);
 escText($("chainState"),ev.transition_chain&&ev.transition_chain.valid?"VALID":"CHECK");
 var nd=$("notDoing");nd.replaceChildren();var items=[];
 if(!state.changes_model_context)items.push("Not injecting anything into your agent's prompt");
 if(!state.makes_extra_provider_calls)items.push("Not making extra model calls");
 items.push("Not replacing or deleting your host's native memory");
 if(mode==="capture")items.push("Not computing recall previews yet");
 items.forEach(function(t){var li=document.createElement("li");li.textContent=t;nd.appendChild(li)});
 var next={off:["Start a trial from the CLI before using this dashboard.","overview"],capture:["Review candidates, approve trusted items, then enter preview.","memory"],preview:["Observe at least one recall preview, then consider a limited canary.","preview"],canary:["Complete the bounded canary before considering activation.","switch"],active:["Inspect the evidence AetnaMem is preserving.","value"]}[mode];
 escText($("nextText"),next[0]);$("nextBtn").onclick=function(){show(next[1])};
 renderMemory();renderGates();renderChart();
 $("previewBtn").disabled=mode!=="capture"||!(state.readiness&&state.readiness.ready_for_preview);
 $("canaryBtn").disabled=mode!=="preview"||!(state.readiness&&state.readiness.ready_for_canary);
 $("activeBtn").disabled=mode!=="canary"||!(state.readiness&&state.readiness.ready_for_active)
}
function renderMemory(){
 var c=counts(),options=[["all","All",c.candidate+c.approved+c.rejected],["candidate","Candidates",c.candidate],["approved","Approved",c.approved],["rejected","Rejected",c.rejected]];
 var fs=$("filters");fs.replaceChildren();options.forEach(function(o){var b=document.createElement("button");b.className="filter";b.setAttribute("aria-pressed",filter===o[0]?"true":"false");b.textContent=o[1]+" · "+o[2];b.onclick=function(){filter=o[0];renderMemory()};fs.appendChild(b)});
 var list=$("memoryList");list.replaceChildren();var rows=candidates.filter(function(x){return filter==="all"||x.status===filter});
 if(!rows.length){var e=document.createElement("div");e.className="empty";e.textContent="No "+(filter==="all"?"":filter+" ")+"memory candidates yet.";list.appendChild(e);return}
 rows.forEach(function(x){var wrap=document.createElement("div");wrap.className="mem";var row=document.createElement("div");row.className="memrow";
  var text=document.createElement("div");text.className="memtext";var content=document.createElement("div");content.textContent=x.content;
  var why=document.createElement("div");why.className="why mono";why.textContent=(x.source_type||"source")+" · "+(x.trust_tier||"trust unknown")+" · "+short(x.content_sha256);
  text.append(content,why);var st=document.createElement("span");st.className="status "+x.status;st.textContent=x.status;row.append(text,st);
  if(x.status==="candidate"){var acts=document.createElement("div");acts.className="acts";[["Approve",true,"ok"],["Reject",false,""]].forEach(function(a){var b=document.createElement("button");b.textContent=a[0];b.className=a[2];b.onclick=function(){review(x.id,a[1])};acts.appendChild(b)});row.appendChild(acts)}
  wrap.appendChild(row);list.appendChild(wrap)
 })
}
function renderGates(){
 var box=$("gates");box.replaceChildren();var readiness=state.readiness||{},ev=state.evidence||{},checks=[
  ["Transition evidence",!!(ev.transition_chain&&ev.transition_chain.valid),ev.transition_chain&&ev.transition_chain.valid?"chain valid":"chain invalid"],
  ["Approved memory",counts().approved>0,counts().approved+" approved"],
  ["Recall preview",num(ev.previews)>0,num(ev.previews)+" recorded"],
  ["Canary completed",readiness.ready_for_active,num(ev.shown_canary_exposures)+" of "+num(state.canary_turns)+" shown"]
 ];checks.forEach(function(x){var row=document.createElement("div");row.className="gate";var g=document.createElement("span");g.className="g "+(x[1]?"pass":"pend");g.textContent=x[1]?"PASS":"PEND";var label=document.createElement("span");label.textContent=x[0];var m=document.createElement("span");m.className="m mono";m.textContent=x[2];row.append(g,label,m);box.appendChild(row)});
 if(readiness.reasons&&readiness.reasons.length){var p=document.createElement("p");p.className="why";p.textContent="Next: "+readiness.reasons.join("; ");box.appendChild(p)}
}
function renderChart(){
 var ev=state.evidence||{},c=counts(),values=[c.candidate+c.approved+c.rejected,c.approved,num(ev.previews),num(ev.shown_exposures)],labels=["captured","approved","previews","shown"],max=Math.max.apply(null,[1].concat(values)),g=$("funnelBars");g.replaceChildren();
 values.forEach(function(v,i){var x=95+i*155,h=130*v/max,y=190-h;var r=document.createElementNS("http://www.w3.org/2000/svg","rect");r.setAttribute("x",x);r.setAttribute("y",y);r.setAttribute("width","72");r.setAttribute("height",h);r.setAttribute("rx","5");r.setAttribute("class","bar");var val=document.createElementNS("http://www.w3.org/2000/svg","text");val.setAttribute("x",x+36);val.setAttribute("y",Math.max(20,y-8));val.setAttribute("text-anchor","middle");val.setAttribute("class","chartvalue");val.textContent=String(v);var lab=document.createElementNS("http://www.w3.org/2000/svg","text");lab.setAttribute("x",x+36);lab.setAttribute("y","214");lab.setAttribute("text-anchor","middle");lab.textContent=labels[i];g.append(r,val,lab)})
}
async function review(id,approve){try{clearError();await post("/api/review",{candidate_ids:[id],approve:approve});await reload()}catch(e){showError(e)}}
async function setMode(mode,turns){
 var body={mode:mode};if(mode==="canary"||mode==="active"){var expected=state.host||"";var entered=prompt("Type the host name '"+expected+"' to confirm:");if(entered===null)return;body.confirm_host=entered}if(turns)body.turns=turns;
 try{clearError();await post("/api/mode",body);await reload();show("switch")}catch(e){showError(e)}
}
$("offBtn").onclick=function(){if(confirm("Stop AetnaMem influencing your agent immediately? Your host keeps running."))setMode("off")};
$("previewBtn").onclick=function(){setMode("preview")};$("canaryBtn").onclick=function(){setMode("canary",20)};$("activeBtn").onclick=function(){setMode("active")};
async function reload(){var out=await Promise.all([get("/api/status"),get("/api/candidates")]);state=out[0];candidates=out[1].candidates||[];render()}
async function init(){try{csrf=(await get("/api/session")).csrf_token;await reload()}catch(e){showError(e)}}
init()
})();
</script>
</body>
</html>
"""
