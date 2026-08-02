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
.repolink{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:9px;
padding:7px 11px;color:var(--ink);background:var(--card);font-size:12px;font-weight:800;text-decoration:none}
.repolink:hover{border-color:var(--brand);color:var(--brand)}.repolink svg{width:16px;height:16px;fill:currentColor}
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
.backdrop{display:none;position:fixed;inset:0;background:#07110f99;z-index:20;overflow:hidden}
.backdrop.show{display:block}.drawer{position:fixed;right:0;top:0;bottom:0;height:100vh;height:100dvh;
max-height:100vh;max-height:100dvh;width:min(720px,94vw);background:var(--bg);box-shadow:-20px 0 60px #0004;
padding:0 22px 28px;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;scrollbar-gutter:stable}
.drawerhead{display:flex;gap:14px;align-items:start;position:sticky;top:0;background:var(--bg);
padding:22px 0 16px;z-index:2;border-bottom:1px solid var(--line)}.drawerhead>div{min-width:0;flex:1}
.drawerhead h2{font-size:22px;margin:2px 0}.close{margin-left:auto;flex:0 0 auto;width:38px;height:38px;
border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:21px}
.auditorbody{padding-top:18px}.recordcontent{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;
max-height:150px;overflow:auto;padding-right:6px}.evidencegrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
gap:9px}.evidence{border:1px solid var(--line);background:var(--card);border-radius:10px;padding:11px;
min-width:0}.evidence span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;
letter-spacing:.06em}.evidence b{display:block;margin-top:3px;overflow-wrap:anywhere;word-break:break-word}
.evidence b.mono{word-break:break-all}.chain{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));
gap:6px;align-items:stretch;padding:4px 0}.chainstep{min-width:0;overflow:hidden;border:1px solid var(--line);
border-radius:9px;padding:9px;background:var(--card);font-size:11px}.chainstep b{display:block;font-size:12px}
.chainstep span{display:block;margin-top:2px;overflow-wrap:anywhere;word-break:break-word}
.chainstep.ok{border-color:var(--good);background:var(--good-soft)}.chainstep.missing{color:var(--muted)}
.timeline{border-left:2px solid var(--line);margin-left:7px;padding-left:17px}.event{position:relative;
padding:0 0 17px}.event:before{content:"";position:absolute;left:-23px;top:5px;width:10px;height:10px;
border-radius:50%;background:var(--brand);border:2px solid var(--bg)}.event b{display:block}.event p{margin:2px 0;
color:var(--muted);font-size:12px}.downloads{display:flex;gap:8px;flex-wrap:wrap}.downloads a{display:inline-flex;
text-decoration:none}.delivery{border-top:1px solid var(--line);padding:11px 0}.delivery:first-child{border-top:0}
.delivery b{display:block}.integrity{color:var(--good);font-weight:800}.integrity.bad{color:var(--bad)}
.reviewhead{display:flex;align-items:center;gap:9px}.reviewhead .secondary{margin-left:auto;padding:6px 10px;
font-size:12px}.reviewcount{display:inline-grid;place-items:center;
min-width:24px;height:24px;border-radius:99px;padding:0 7px;background:var(--warn-soft);color:var(--warn);
font-size:11px;font-weight:850}.reviewitem{border-top:1px solid var(--line);padding:15px 0}
.reviewitem:first-child{border-top:0}.reviewcontent{margin:0 0 8px;white-space:pre-wrap;
overflow-wrap:anywhere}.reviewmeta{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:11px}
.reviewcompare{display:grid;grid-template-columns:minmax(220px,.8fr) minmax(0,1.2fr);gap:12px;margin:10px 0 12px}
.reviewpane{min-width:0;border:1px solid var(--line);border-radius:11px;background:var(--bg);padding:12px}
.reviewpane h3{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.reviewimage{display:block;width:100%;max-height:320px;object-fit:contain;border-radius:8px;background:#0a0f0e}
.reviewboundary{margin:9px 0 0;color:var(--muted);font-size:12px}.reviewboundary strong{color:var(--ink)}
.previewstatus{margin:8px 0 0;font-size:12px;color:var(--muted)}.previewstatus.bad{color:var(--bad)}
.reviewactions{display:flex;gap:8px;flex-wrap:wrap}.reviewactions button{border-radius:9px;padding:9px 13px;
font-weight:750}.approve{background:var(--good);border-color:var(--good)}
.reviewactions button:disabled{opacity:.48;cursor:not-allowed;filter:none}
.reject{background:var(--card);border:1px solid var(--bad);color:var(--bad)}.reject:hover{background:var(--bad-soft)}
.auditcard{margin-top:18px;padding:0;overflow:hidden}.audithead{padding:20px 22px 15px;border-bottom:1px solid var(--line);
display:flex;gap:18px;align-items:start}.audithead>div:first-child{flex:1}.audittoolbar{display:flex;gap:7px;flex-wrap:wrap;
justify-content:flex-end}.auditfilters{padding:16px 22px;display:grid;grid-template-columns:2fr repeat(3,minmax(145px,1fr));
gap:10px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--card) 88%,var(--bg))}
.field{min-width:0}.field label{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.07em;
font-weight:800;color:var(--muted);margin:0 0 4px}.field input,.field select{width:100%;border:1px solid var(--line);
border-radius:8px;background:var(--card);color:var(--ink);padding:9px 10px;min-height:39px}.filteractions{display:flex;
gap:8px;align-items:end}.quickrange{padding:10px 22px;border-bottom:1px solid var(--line);display:flex;gap:7px;
align-items:center;flex-wrap:wrap}.quickrange button{border:1px solid var(--line);background:var(--card);color:var(--ink);
border-radius:99px;padding:5px 10px;font-size:11px}.quickrange button:hover{border-color:var(--brand);color:var(--brand)}
.histogram{height:100px;padding:14px 22px 8px;display:flex;gap:3px;align-items:end;border-bottom:1px solid var(--line)}
.histbar{flex:1;min-width:3px;max-width:28px;background:var(--brand);opacity:.72;border-radius:3px 3px 0 0;
border:0;padding:0}.histbar:hover{opacity:1}.auditmeta{padding:10px 22px;display:flex;gap:12px;align-items:center;
border-bottom:1px solid var(--line);color:var(--muted);font-size:12px}.auditmeta .grow{flex:1}.auditviewport{overflow:auto;
max-height:600px}.audittable{width:100%;border-collapse:separate;border-spacing:0;min-width:1040px}.audittable th{
position:sticky;top:0;z-index:1;background:var(--card);text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);
font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}.audittable td{padding:10px 12px;
border-bottom:1px solid var(--line);vertical-align:top;font-size:12px}.audittable tr:hover td{background:var(--brand-soft)}
.eventbutton{border:0;background:none;color:var(--ink);padding:0;font-weight:750;text-align:left}.pivot{border:0;
background:none;color:var(--blue);padding:0;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.auditpager{padding:12px 22px;display:flex;align-items:center;gap:8px}.eventpayload{white-space:pre-wrap;word-break:break-word;
background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:12px;font-size:11px;max-height:320px;overflow:auto}
.savedview{max-width:190px}.integritychip{display:inline-flex;gap:6px;align-items:center;color:var(--good);font-weight:800}
.integritychip.bad{color:var(--bad)}
.productfoot{margin-top:22px;padding:20px 22px;display:flex;gap:22px;align-items:center;background:var(--card);
border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}.productfoot>div:first-child{flex:1}
.productfoot b{display:block;font-size:16px;letter-spacing:-.015em}.productfoot p{margin:3px 0 0;color:var(--muted)}
.productlinks{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.productlinks a{color:var(--blue);
text-decoration:none;font-weight:750;white-space:nowrap}.productlinks a:hover{text-decoration:underline}.productlinks span{color:var(--line)}
@media(max-width:780px){.wrap{padding:0 14px}.hero{grid-template-columns:1fr;padding:20px}.reviewcompare{grid-template-columns:1fr}
.actions{width:100%}.actions button{flex:1}.grid{grid-template-columns:1fr}.metrics{
grid-template-columns:repeat(2,1fr)}header .small{display:none}.evidencegrid{grid-template-columns:1fr}
.chain{grid-template-columns:repeat(2,minmax(0,1fr))}.drawer{width:100vw;padding-left:16px;padding-right:16px}
.auditfilters{grid-template-columns:1fr}.audithead{display:block}.audittoolbar{justify-content:flex-start;margin-top:12px}
.productfoot{display:block}.productlinks{justify-content:flex-start;margin-top:12px}.repolink span{display:none}}
</style>
</head>
<body>
<header><div class="wrap head">
  <div class="logo"><span>Aetna</span>Mem</div>
  <div class="small">OpenClaw memory</div>
  <div class="grow"></div>
  <a class="repolink" href="https://github.com/aetna000/aetnamem" target="_blank" rel="noopener noreferrer" aria-label="View AetnaMem on GitHub">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 .7a11.5 11.5 0 0 0-3.64 22.4c.58.1.79-.25.79-.56v-2.23c-3.22.7-3.9-1.37-3.9-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.78 1.2 1.78 1.2 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.57-.29-5.28-1.29-5.28-5.68 0-1.26.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.16 1.18a10.9 10.9 0 0 1 5.76 0c2.19-1.49 3.16-1.18 3.16-1.18.63 1.58.23 2.75.11 3.04.74.8 1.19 1.82 1.19 3.08 0 4.4-2.71 5.38-5.29 5.67.42.36.79 1.06.79 2.14v3.18c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z"/></svg>
    <span>Star on GitHub</span>
  </a>
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

      <section class="card" id="reviewCard">
        <div class="reviewhead"><h2>Needs approval</h2><span class="reviewcount" id="reviewCount">0</span><button class="secondary" id="reviewRefresh" type="button">Refresh</button></div>
        <p class="sub">External observations stay out of agent recall until you approve them. Rejection permanently purges the candidate content.</p>
        <div id="reviews"><div class="empty">Checking for quarantined memories…</div></div>
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

  <section class="card auditcard" id="auditExplorer">
    <div class="audithead">
      <div><div class="eyebrow">Global evidence investigation</div><h2>Audit Explorer</h2>
      <p class="sub">Search the complete memory audit chain, narrow the evidence, then drill into records, sessions and exact events.</p></div>
      <div class="audittoolbar">
        <select class="secondary savedview" id="auditSaved"><option value="">Saved views…</option></select>
        <button class="secondary" id="auditSave" type="button">Save view</button>
        <button class="secondary" id="auditReset" type="button">Reset</button>
      </div>
    </div>
    <div class="quickrange"><span class="small">Time range</span>
      <button type="button" data-range="15">15 minutes</button><button type="button" data-range="60">1 hour</button>
      <button type="button" data-range="1440">24 hours</button><button type="button" data-range="10080">7 days</button>
      <button type="button" data-range="0">All time</button>
      <span class="small" style="margin-left:10px">Evidence stage</span>
      <button type="button" data-event-pattern="memory.record*">Admission</button>
      <button type="button" data-event-pattern="memory.recall">Recall</button>
      <button type="button" data-event-pattern="memory.context_injected">Injection</button>
      <button type="button" data-event-pattern="agent.response_after_memory">Response</button>
      <button type="button" data-event-pattern="memory.forget">Deletion</button>
    </div>
    <div class="auditfilters">
      <div class="field"><label for="auditQuery">Search event IDs, payloads and evidence</label><input id="auditQuery" placeholder="memory, model, digest, ID…"></div>
      <div class="field"><label for="auditType">Event type</label><select id="auditType"><option value="">All event types</option></select></div>
      <div class="field"><label for="auditActor">Actor</label><select id="auditActor"><option value="">All actors</option></select></div>
      <div class="field"><label for="auditSession">Session ID</label><input id="auditSession" placeholder="agent:main:…"></div>
      <div class="field"><label for="auditRecord">Record ID</label><input id="auditRecord" placeholder="rec_…"></div>
      <div class="field"><label for="auditSince">From</label><input id="auditSince" type="datetime-local"></div>
      <div class="field"><label for="auditUntil">To</label><input id="auditUntil" type="datetime-local"></div>
      <div class="filteractions"><button class="primary" id="auditRun" type="button">Run search</button></div>
    </div>
    <div class="histogram" id="auditHistogram" aria-label="Audit events over time"></div>
    <div class="auditmeta"><span id="auditIntegrity" class="integritychip">Checking integrity…</span>
      <span id="auditCount">—</span><span class="mono" id="auditDigest"></span><span class="grow"></span>
      <select id="auditDirection" class="secondary"><option value="desc">Newest first</option><option value="asc">Oldest first</option></select>
      <select id="auditLimit" class="secondary"><option>50</option><option selected>100</option><option>250</option><option>500</option></select>
    </div>
    <div class="auditviewport"><table class="audittable"><thead><tr><th>Time</th><th>Event</th><th>Actor</th><th>Record</th><th>Session / turn</th><th>Evidence ID</th><th>Integrity</th></tr></thead>
      <tbody id="auditRows"><tr><td colspan="7" class="empty">Loading audit evidence…</td></tr></tbody></table></div>
    <div class="auditpager"><button class="secondary" id="auditBack" type="button" disabled>Previous</button>
      <button class="secondary" id="auditNext" type="button" disabled>Next</button><span class="small" id="auditPage">Page 1</span>
      <span class="grow"></span><a class="secondary auditexport" data-format="csv">CSV</a><a class="secondary auditexport" data-format="json">JSON</a>
      <a class="secondary auditexport" data-format="ndjson">NDJSON</a><a class="secondary auditexport" data-format="text">Text</a></div>
  </section>

  <footer class="productfoot">
    <div>
      <b>AetnaMem — governed memory for AI agents</b>
      <p>Search what an agent remembers, approve what becomes trusted, and follow the evidence behind every recall.</p>
    </div>
    <nav class="productlinks" aria-label="AetnaMem resources">
      <a href="https://github.com/aetna000/aetnamem" target="_blank" rel="noopener noreferrer">GitHub repository</a><span>·</span>
      <a href="https://github.com/aetna000/aetnamem/blob/main/docs/openclaw-setup.md" target="_blank" rel="noopener noreferrer">OpenClaw guide</a><span>·</span>
      <a href="https://github.com/aetna000/aetnamem/blob/main/docs/audit-search.md" target="_blank" rel="noopener noreferrer">Audit guide</a><span>·</span>
      <a href="https://github.com/aetna000/aetnamem/issues" target="_blank" rel="noopener noreferrer">Feedback</a>
    </nav>
  </footer>
</main>
<div class="backdrop" id="auditorBackdrop" aria-hidden="true">
  <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="auditorTitle">
    <div class="drawerhead">
      <div><div class="eyebrow">Auditor record history</div><h2 id="auditorTitle">Loading evidence…</h2>
      <div class="mono small" id="auditorId"></div></div>
      <button class="close" id="auditorClose" aria-label="Close record history">×</button>
    </div>
    <div class="auditorbody" id="auditorBody"><div class="empty">Loading the verified audit chain…</div></div>
  </aside>
</div>
<script>
(function(){
"use strict";
var state=null,reviewQueue={records:[]},csrf="",progressTimer=null,progressStarted=0;
var auditCursors=[null],auditPageIndex=0,auditLast=null,auditFacetsLoaded=false;
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
function displayTime(value){if(!value)return "not recorded";var date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString([], {dateStyle:"medium",timeStyle:"short"})}
function evidence(label,value,mono){var box=element("div","evidence"),name=element("span","",label),body=element("b",mono?"mono":"",value||"not recorded");box.append(name,body);return box}
function chainStep(label,ok,detail){var box=element("div","chainstep "+(ok?"ok":"missing"));box.append(element("b","",label),element("span","",detail));return box}
function isoInput(value){if(!value)return "";var d=new Date(value);return Number.isNaN(d.getTime())?"":new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}
function auditFilters(){
 return {query:$("auditQuery").value.trim(),event_type:$("auditType").value,actor:$("auditActor").value,
  session_id:$("auditSession").value.trim(),record_id:$("auditRecord").value.trim(),
  since:$("auditSince").value?new Date($("auditSince").value).toISOString():"",
  until:$("auditUntil").value?new Date($("auditUntil").value).toISOString():"",direction:$("auditDirection").value}
}
function auditQueryString(filters,extra){var p=new URLSearchParams();Object.keys(filters).forEach(function(k){if(filters[k])p.set(k,filters[k])});Object.keys(extra||{}).forEach(function(k){if(extra[k]!=null&&extra[k]!=="")p.set(k,extra[k])});return p.toString()}
function pivotAudit(field,value){if(!value)return;if(field==="record")$("auditRecord").value=value;if(field==="session")$("auditSession").value=value;if(field==="actor")$("auditActor").value=value;if(field==="type")$("auditType").value=value;auditSearch(true)}
function auditFacetOptions(facets){
 if(!facets)return;var type=$("auditType"),actor=$("auditActor"),selectedType=type.value,selectedActor=actor.value;
 type.replaceChildren(new Option("All event types",""));(facets.event_types||[]).forEach(function(row){type.appendChild(new Option(row.value+" ("+number(row.count)+")",row.value))});type.value=selectedType;
 actor.replaceChildren(new Option("All actors",""));(facets.actors||[]).forEach(function(row){actor.appendChild(new Option(row.value+" ("+number(row.count)+")",row.value))});actor.value=selectedActor;auditFacetsLoaded=true
}
function renderHistogram(rows){var box=$("auditHistogram");box.replaceChildren();if(!rows||!rows.length){box.appendChild(element("div","empty","No events in this time range."));return}var max=Math.max.apply(null,rows.map(function(r){return Number(r.count||0)}));rows.forEach(function(row){var bar=element("button","histbar");bar.type="button";bar.style.height=Math.max(4,Math.round(Number(row.count||0)/max*78))+"px";bar.title=row.bucket+" · "+number(row.count)+" events";bar.setAttribute("aria-label",bar.title);bar.onclick=function(){var start=new Date(row.bucket+(row.bucket.length===13?":00:00Z":"T00:00:00Z")),end=new Date(start.getTime()+(row.bucket.length===13?3600000:86400000)-1);$("auditSince").value=isoInput(start);$("auditUntil").value=isoInput(end);auditSearch(true)};box.appendChild(bar)})}
function auditSummary(row){var p=row.payload||{};if(row.event_type==="memory.recall")return number(p.returned_ids&&p.returned_ids.length)+" returned / "+number(p.candidate_count)+" candidates";if(row.event_type==="memory.context_injected")return number(p.record_ids&&p.record_ids.length)+" memories injected";if(row.event_type==="agent.response_after_memory")return "response "+shortDigest(p.response_sha256);if(p.operation)return String(p.operation);return Object.keys(p).slice(0,3).join(", ")||"Open evidence"}
function inspectAuditEvent(row){
 document.body.style.overflow="hidden";$("auditorBackdrop").classList.add("show");$("auditorBackdrop").setAttribute("aria-hidden","false");$("auditorBackdrop").querySelector(".drawer").scrollTop=0;text("auditorTitle",row.event_type);text("auditorId",row.event_id);
 var body=$("auditorBody");body.replaceChildren();var integrity=element("p","integrity","✓ Event is bound to the verified chain");body.appendChild(integrity);
 var overview=element("section","card"),grid=element("div","evidencegrid");overview.append(element("h2","","Event details"),element("p","sub","Pivot from any linked identifier to narrow the global investigation."));grid.append(evidence("Sequence",String(row.sequence),true),evidence("Time",displayTime(row.created_at),false),evidence("Actor",row.actor,false),evidence("Event ID",row.event_id,true),evidence("Previous hash",row.prev_hash,true),evidence("Event hash",row.event_hash,true));overview.appendChild(grid);body.appendChild(overview);
 var pivots=element("section","card"),links=element("div","downloads"),payloadValue=row.payload||{};pivots.append(element("h2","","Follow linked evidence"));[["record",row.record_id,"Record"],["session",row.session_id,"Session"],["actor",row.actor,"Actor"],["type",row.event_type,"Event type"]].forEach(function(v){if(!v[1])return;var b=element("button","secondary",v[2]+": "+v[1]);b.onclick=function(){closeAuditor();pivotAudit(v[0],v[1])};links.appendChild(b)});
 var linkedRecords=[];["record_id","record_ids","returned_ids","injected_record_ids","purged_record_ids","supersedes"].forEach(function(key){var value=payloadValue[key];(Array.isArray(value)?value:[value]).filter(Boolean).forEach(function(id){if(String(id).indexOf("rec_")===0&&linkedRecords.indexOf(String(id))<0)linkedRecords.push(String(id))})});linkedRecords.forEach(function(id){var b=element("button","secondary","Memory: "+id);b.onclick=function(){inspectRecord(id)};links.appendChild(b)});
 ["retrieval_id","run_id","outcome_id","transaction_id","operation_id","artifact_id","observation_id"].forEach(function(key){if(!payloadValue[key])return;var id=String(payloadValue[key]),b=element("button","secondary",key.replace("_id","")+": "+id);b.onclick=function(){closeAuditor();$("auditQuery").value=id;auditSearch(true)};links.appendChild(b)});if(row.record_id){var inspect=element("button","primary","Open record history");inspect.onclick=function(){inspectRecord(row.record_id)};links.appendChild(inspect)}pivots.appendChild(links);body.appendChild(pivots);
 var payload=element("section","card");payload.append(element("h2","","Canonical payload"),element("p","sub","The exact structured evidence covered by the event hash."),element("pre","eventpayload mono",JSON.stringify(row.payload||{},null,2)));body.appendChild(payload)
}
function renderAudit(report){
 auditLast=report;auditFacetOptions(report.facets);renderHistogram(report.histogram);var rows=$("auditRows");rows.replaceChildren();
 if(!(report.events||[]).length){var tr=element("tr"),td=element("td","empty","No audit events match these filters.");td.colSpan=7;tr.appendChild(td);rows.appendChild(tr)}
 (report.events||[]).forEach(function(row){var tr=element("tr"),time=element("td","",displayTime(row.created_at)),event=element("td"),eventBtn=element("button","eventbutton",row.event_type),summary=element("div","small",auditSummary(row));eventBtn.onclick=function(){inspectAuditEvent(row)};event.append(eventBtn,summary);
  var actor=element("td"),actorBtn=element("button","pivot",row.actor);actorBtn.onclick=function(){pivotAudit("actor",row.actor)};actor.appendChild(actorBtn);
  var record=element("td");if(row.record_id){var recordBtn=element("button","pivot mono",row.record_id);recordBtn.onclick=function(){inspectRecord(row.record_id)};record.appendChild(recordBtn)}else record.textContent="—";
  var session=element("td");if(row.session_id){var sessionBtn=element("button","pivot mono",row.session_id);sessionBtn.onclick=function(){pivotAudit("session",row.session_id)};session.appendChild(sessionBtn)}else session.textContent="—";if(row.turn_id)session.appendChild(element("div","small mono",row.turn_id));
  tr.append(time,event,actor,record,session,element("td","mono",row.event_id),element("td","integrity","verified"));rows.appendChild(tr)
 });
 $("auditIntegrity").className="integritychip"+(report.audit_chain_valid?"":" bad");text("auditIntegrity",report.audit_chain_valid?"✓ Chain verified":"✕ Verification failed");text("auditCount",number(report.matched_total)+" matching · "+number((report.events||[]).length)+" on this page");text("auditDigest",shortDigest(report.result_digest));text("auditPage","Page "+(auditPageIndex+1));$("auditBack").disabled=auditPageIndex===0;$("auditNext").disabled=!report.has_more;
 document.querySelectorAll(".auditexport").forEach(function(a){a.href="/api/mirror/audit-export?"+auditQueryString(auditFilters(),{format:a.dataset.format})})
}
async function loadAudit(includeFacets){
 clearError();$("auditRows").classList.add("loading");try{var extra={limit:$("auditLimit").value,include_facets:includeFacets?1:0},cursor=auditCursors[auditPageIndex];if(cursor!=null)extra.cursor=cursor;var report=await get("/api/mirror/audit?"+auditQueryString(auditFilters(),extra));renderAudit(report)}catch(error){showError(error)}finally{$("auditRows").classList.remove("loading")}
}
function auditSearch(reset){if(reset){auditCursors=[null];auditPageIndex=0}loadAudit(!auditFacetsLoaded||reset)}
function savedViews(){try{return JSON.parse(localStorage.getItem("aetnamem-audit-views")||"[]")}catch(_){return []}}
function renderSavedViews(){var select=$("auditSaved");select.replaceChildren(new Option("Saved views…",""));savedViews().forEach(function(view,index){select.appendChild(new Option(view.name,String(index)))})}
function applyAuditFilters(f){$("auditQuery").value=f.query||"";$("auditType").value=f.event_type||"";$("auditActor").value=f.actor||"";$("auditSession").value=f.session_id||"";$("auditRecord").value=f.record_id||"";$("auditSince").value=isoInput(f.since);$("auditUntil").value=isoInput(f.until);$("auditDirection").value=f.direction||"desc"}
function closeAuditor(){$("auditorBackdrop").classList.remove("show");$("auditorBackdrop").setAttribute("aria-hidden","true");document.body.style.overflow=""}
async function inspectRecord(recordId){
 clearError();document.body.style.overflow="hidden";$("auditorBackdrop").classList.add("show");$("auditorBackdrop").setAttribute("aria-hidden","false");
 $("auditorBackdrop").querySelector(".drawer").scrollTop=0;text("auditorTitle","Memory record");text("auditorId",recordId);$("auditorBody").replaceChildren(element("div","empty","Verifying the complete record history…"));
 try{
  var report=await get("/api/mirror/record?record_id="+encodeURIComponent(recordId)),record=report.record||{},p=report.provenance||{},life=report.lifecycle||{},deliveries=report.deliveries||[],timeline=report.timeline||[],body=$("auditorBody");body.replaceChildren();
  var integrity=element("p","integrity"+(report.audit_chain_valid?"":" bad"),report.audit_chain_valid?"✓ Audit chain verified":"✕ Audit chain verification failed");body.appendChild(integrity);
  var memoryCard=element("section","card");memoryCard.append(element("h2","","Stored memory"),element("p","recordcontent",record.content||"The memory content was purged; retained audit evidence is shown below."));body.appendChild(memoryCard);
  var chain=element("div","chain");var delivered=deliveries.some(function(d){return !!d.context_injected_at}),responded=deliveries.some(function(d){return !!d.response_sha256});
  chain.append(chainStep("Source",!!p.source_message_sha256,shortDigest(p.source_message_sha256)),chainStep("Interpret",!!p.interpreting_model,p.interpreting_model||"native import"),chainStep("Admit",!!life.created_at,displayTime(life.created_at)),chainStep("Recall",deliveries.length>0,deliveries.length+" attempt"+(deliveries.length===1?"":"s")),chainStep("Inject",delivered,delivered?"context receipt":"not recorded"),chainStep("Reply",responded,responded?"fingerprint recorded":"not recorded"));
  var chainCard=element("section","card");chainCard.append(element("h2","","Evidence chain"),element("p","sub","Source → interpretation → admission → recall → context injection → agent response"),chain);body.appendChild(chainCard);
  var prov=element("section","card"),provGrid=element("div","evidencegrid");prov.append(element("h2","","Source and interpretation"),element("p","sub","Digests prove identity without exposing the original message."));
  provGrid.append(evidence("Source-message SHA-256",p.source_message_sha256,true),evidence("Interpreting model",p.interpreting_model||"Native OpenClaw import",false),evidence("Source binding",p.source_binding||p.interpretation_assurance,false),evidence("Native source",p.native_path||"Not a native-file import",true),evidence("Episode",p.episode_id,true),evidence("Memory plane",p.plane,false));prov.appendChild(provGrid);body.appendChild(prov);
  var lifecycle=element("section","card"),lifeGrid=element("div","evidencegrid");lifecycle.append(element("h2","","Record lifecycle"),element("p","sub","Canonical state changes preserved in chronological audit evidence."));lifeGrid.append(evidence("Status",report.status,false),evidence("Created",displayTime(life.created_at),false),evidence("Superseded",life.superseded_at?displayTime(life.superseded_at):"Not superseded",false),evidence("Deleted",life.deleted_at?displayTime(life.deleted_at):"Not deleted",false));lifecycle.appendChild(lifeGrid);body.appendChild(lifecycle);
  var considered=deliveries.length,returned=deliveries.filter(function(d){return d.returned}).length,injected=deliveries.filter(function(d){return d.context_injected_at}).length,bound=deliveries.filter(function(d){return d.response_sha256}).length;
  var deliveryCard=element("section","card"),deliveryStats=element("div","evidencegrid");deliveryCard.append(element("h2","","Retrieval attempts involving this record"),element("p","sub","Candidate scoring, return, context injection and response binding are separate evidence states."));deliveryStats.append(evidence("Considered",String(considered),true),evidence("Returned",String(returned),true),evidence("Injected",String(injected),true),evidence("Response-bound",String(bound),true));deliveryCard.appendChild(deliveryStats);
  if(!deliveries.length)deliveryCard.appendChild(element("div","empty","This record has not appeared in a recorded recall."));
  deliveries.forEach(function(d){var item=element("div","delivery");item.append(element("b","","Rank "+d.rank+" · score "+d.score+(d.returned?" · returned":" · candidate only")),element("div","small",displayTime(d.recalled_at)+" · "+(d.session_id||"no session")),element("div","small","Context injection: "+(d.context_injected_at?displayTime(d.context_injected_at):"not recorded")+(d.link_assurance?" · "+d.link_assurance:"")),element("div","small mono","Agent response digest: "+(d.response_sha256||"not recorded")+(d.response_link_assurance?" · "+d.response_link_assurance:"")));deliveryCard.appendChild(item)});body.appendChild(deliveryCard);
  var timeCard=element("section","card"),timeBox=element("div","timeline");timeCard.append(element("h2","","Complete chronological history"),element("p","sub",timeline.length+" linked evidence event"+(timeline.length===1?"":"s")+"."));
  timeline.forEach(function(e){var item=element("div","event");item.append(element("b","",e.title||e.type),element("p","",e.detail||""),element("div","small mono",displayTime(e.at)+" · "+(e.actor||"unknown actor")+" · "+(e.event_id||"no evidence ID")+(e.session_id?" · "+e.session_id:"")));timeBox.appendChild(item)});if(!timeline.length)timeBox.appendChild(element("div","empty","No linked events were retained."));timeCard.appendChild(timeBox);body.appendChild(timeCard);
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
function renderReviews(){
 var box=$("reviews"),rows=Array.isArray(reviewQueue.records)?reviewQueue.records:[];box.replaceChildren();text("reviewCount",rows.length);
 if(!rows.length){box.appendChild(element("div","empty","Nothing is waiting for approval."));return}
 rows.forEach(function(row){
  var item=element("div","reviewitem"),content=element("p","reviewcontent",row.content||"Content unavailable"),meta=element("div","reviewmeta");
  meta.append(element("span","pill",row.media&&row.media.modality?row.media.modality:(row.scope||"observation")),element("span","small",displayTime(row.created_at)));
  var inspect=element("button","recordlink mono",row.record_id);inspect.type="button";inspect.onclick=function(){inspectRecord(row.record_id)};meta.appendChild(inspect);
  if(row.media&&row.media.extractor){var extractor=row.media.extractor;meta.append(element("span","small",[extractor.provider,extractor.model,extractor.version].filter(Boolean).join(" / ")||"extractor recorded"))}
  var isImage=Boolean(row.media&&row.media.modality==="image"),actions=element("div","reviewactions"),approve=element("button","primary approve",isImage?"Approve description as memory":"Approve as memory"),reject=element("button","reject","Reject and purge");
  approve.type="button";reject.type="button";approve.onclick=function(){reviewRecord(row,"approve")};reject.onclick=function(){reviewRecord(row,"reject")};
  item.appendChild(meta);
  if(isImage){
   var compare=element("div","reviewcompare"),source=element("section","reviewpane"),remembered=element("section","reviewpane"),image=element("img","reviewimage"),status=element("p","previewstatus","Verifying the exact source image…");
   source.append(element("h3","","Source image being reviewed"));image.alt="Source image bound to this observation";image.src=row.media.preview_url||"";approve.disabled=true;
   image.onload=function(){status.textContent="Source bytes verified against SHA-256 "+String(row.media.media_sha256||"").slice(0,16)+"…";status.className="previewstatus";approve.disabled=false};
   image.onerror=function(){image.remove();status.textContent="The exact source image is unavailable or no longer matches its recorded digest. Approval is disabled.";status.className="previewstatus bad";approve.disabled=true};
   source.append(image,status);remembered.append(element("h3","","What AetnaMem will remember"),content,element("p","reviewboundary","Future agents receive this text description, not the image pixels. The original image remains controlled by OpenClaw."));
   compare.append(source,remembered);item.appendChild(compare)
  }else item.appendChild(content);
  actions.append(approve,reject);item.appendChild(actions);box.appendChild(item)
 })
}
async function reviewRecord(row,decision){
 var approving=decision==="approve",verb=approving?"approve":"reject and permanently purge";
 var subject=row.media&&row.media.modality==="image"?"this exact text description as recallable memory":"this exact memory";
 if(!confirm("Do you want to "+verb+" "+subject+"?\n\n"+(row.content||"")))return;
 try{await working(approving?"Approving memory":"Rejecting memory",approving?"Activating the exact reviewed record and writing an audit event.":"Purging the exact reviewed record and verifying derived-index cleanup.",async function(){await post("/api/mirror/review",{record_id:row.record_id,confirm_record_id:row.record_id,decision:decision});await reload()})}
 catch(error){showError(error)}
}
async function refreshReviews(){
 try{reviewQueue=await get("/api/mirror/reviews");renderReviews()}catch(error){showError(error)}
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
 renderSources(mirror);renderReviews();$("checks").replaceChildren();
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
async function reload(){var values=await Promise.all([get("/api/status"),get("/api/mirror/reviews")]);state=values[0];reviewQueue=values[1];render()}
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
$("reviewRefresh").onclick=refreshReviews;
$("auditRun").onclick=function(){auditSearch(true)};$("auditQuery").addEventListener("keydown",function(event){if(event.key==="Enter")auditSearch(true)});
$("auditDirection").onchange=function(){auditSearch(true)};$("auditLimit").onchange=function(){auditSearch(true)};
$("auditNext").onclick=function(){if(!auditLast||!auditLast.next_cursor)return;auditCursors=auditCursors.slice(0,auditPageIndex+1);auditCursors.push(auditLast.next_cursor);auditPageIndex++;loadAudit(false)};
$("auditBack").onclick=function(){if(auditPageIndex===0)return;auditPageIndex--;loadAudit(false)};
document.querySelectorAll("[data-range]").forEach(function(button){button.onclick=function(){var minutes=Number(button.dataset.range||0),now=new Date();$("auditUntil").value=minutes?isoInput(now):"";$("auditSince").value=minutes?isoInput(new Date(now.getTime()-minutes*60000)):"";auditSearch(true)}});
document.querySelectorAll("[data-event-pattern]").forEach(function(button){button.onclick=function(){var pattern=button.dataset.eventPattern||"",select=$("auditType");if(!Array.from(select.options).some(function(o){return o.value===pattern}))select.appendChild(new Option(pattern,pattern));select.value=pattern;auditSearch(true)}});
$("auditReset").onclick=function(){applyAuditFilters({});auditSearch(true)};
$("auditSave").onclick=function(){var name=prompt("Name this audit view:");if(!name||!name.trim())return;var views=savedViews();views.push({name:name.trim(),filters:auditFilters()});localStorage.setItem("aetnamem-audit-views",JSON.stringify(views));renderSavedViews();$("auditSaved").value=String(views.length-1)};
$("auditSaved").onchange=function(){var view=savedViews()[Number($("auditSaved").value)];if(!view)return;applyAuditFilters(view.filters||{});auditSearch(true)};
$("auditorClose").onclick=closeAuditor;$("auditorBackdrop").addEventListener("click",function(event){if(event.target===$("auditorBackdrop"))closeAuditor()});document.addEventListener("keydown",function(event){if(event.key==="Escape")closeAuditor()});
async function init(){try{csrf=(await get("/api/session")).csrf_token;renderSavedViews();await Promise.all([reload(),loadAudit(true)]);setInterval(refreshReviews,5000)}catch(error){showError(error)}}
init()
})();
</script>
</body>
</html>
"""
