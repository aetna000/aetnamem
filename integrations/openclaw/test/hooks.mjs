#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import path from "node:path";

import plugin from "../dist/index.js";
import { AetnamemClient } from "../dist/src/rpc-client.js";


function fakeApi(config, toolContext = {}) {
  const hooks = new Map();
  const tools = new Map();
  const services = [];
  const logs = [];
  const logger = {
    debug(message) { logs.push(String(message)); },
    info(message) { logs.push(String(message)); },
    warn(message) { logs.push(String(message)); },
    error(message) { logs.push(String(message)); },
  };
  const api = {
    pluginConfig: config,
    logger,
    on(name, handler) { hooks.set(name, handler); },
    registerTool(spec) {
      if (typeof spec === "function") {
        const tool = spec({
          sessionKey: "takeover-1",
          senderIsOwner: true,
          activeModel: { provider: "openai", modelId: "test-model" },
          ...toolContext,
        });
        tools.set(tool.name, tool);
        return;
      }
      tools.set(spec.name, spec);
    },
    registerService(service) { services.push(service); },
  };
  plugin.register(api);
  return { hooks, tools, services, logs };
}

function controlCli(...args) {
  const result = spawnSync("aetnamem", ["control", ...args, "--json"], {
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return result.stdout.trim() ? JSON.parse(result.stdout) : null;
}


const dataDir = mkdtempSync(path.join(tmpdir(), "aetnamem-hooks-"));
const dbPath = path.join(dataDir, "memory.db");
const mediaRoot = path.join(dataDir, "openclaw-media");
mkdirSync(mediaRoot);
process.env.AETNAMEM_OPENCLAW_MEDIA_ROOT = mediaRoot;
const base = {
  command: "aetnamem",
  commandArgs: ["mcp", "--db", dbPath, "--subject", "hook-user"],
  dbPath,
  subject: "hook-user",
  recall: { enabled: true, maxRecords: 3, maxChars: 1200, minScore: 0.3, timeoutMs: 5000 },
  persona: { enabled: true, maxChars: 600, ttlSeconds: 3600 },
  capture: { enabled: true, captureAssistant: false },
  cacheAware: { enabled: true, compactReferences: true },
  tools: { enabled: true },
};

const missingEngine = new AetnamemClient({
  command: `aetnamem-deliberately-missing-${process.pid}`,
  args: ["mcp"],
  defaultTimeoutMs: 1000,
});
await assert.rejects(
  missingEngine.hasTool("memory_recall"),
  /engine executable .* was not found.*Install the engine first.*pip install aetnamem/s,
);
missingEngine.close();

const runtime = fakeApi(base);
const beforePrompt = runtime.hooks.get("before_prompt_build");
const agentEnd = runtime.hooks.get("agent_end");
const beforeWrite = runtime.hooks.get("before_message_write");

try {
  assert.equal(runtime.tools.size, 6);

  const observe = runtime.tools.get("aetnamem_observe");
  const attachmentBytes = Buffer.from("exact uploaded image bytes");
  const attachmentPath = path.join(mediaRoot, "upload.png");
  writeFileSync(attachmentPath, attachmentBytes);
  const messageReceived = runtime.hooks.get("message_received");
  await messageReceived(
    {
      content: "Analyze this upload",
      sessionKey: "takeover-1",
      metadata: {
        mediaPath: attachmentPath,
        mediaPaths: [attachmentPath],
        mediaType: "image/png",
        mediaTypes: ["image/png"],
      },
    },
    { sessionKey: "takeover-1" },
  );
  const autoObserved = await observe.execute("observe-auto-1", {
    text: "The upload contains a geometric logo.",
    modality: "image",
    segment: { region: "whole image", dimensions: { width: 640, height: 480 } },
  });
  assert.equal(autoObserved.details.status, "quarantined");
  assert.equal(autoObserved.details.provenanceSource, "openclaw-upload");
  assert.equal(
    autoObserved.details.mediaSha256,
    createHash("sha256").update(attachmentBytes).digest("hex"),
  );

  // OpenClaw can execute the inbound hook and the later agent tool in
  // separate plugin runtimes. The trusted upload binding must survive that
  // boundary instead of depending on one process-local Map.
  const separateRuntime = fakeApi(base);
  try {
    const crossRuntimeObserved = await separateRuntime.tools
      .get("aetnamem_observe")
      .execute("observe-cross-runtime-1", {
        text: "The separately executed tool can resolve the geometric logo upload.",
        modality: "image",
      });
    assert.equal(crossRuntimeObserved.details.status, "quarantined");
    assert.equal(crossRuntimeObserved.details.provenanceSource, "openclaw-upload");
    assert.equal(crossRuntimeObserved.details.mediaSha256, autoObserved.details.mediaSha256);
  } finally {
    for (const service of separateRuntime.services) await service.stop?.();
  }

  // Internal OpenClaw webchat does not broadcast message_received, and its
  // prompt hooks intentionally omit local attachment paths. The synchronous
  // transcript hook receives the current user message with canonical
  // MediaPath fields before the model can call tools, so it establishes the
  // trusted binding without scraping text or guessing the newest file.
  const webchatBytes = Buffer.from("exact webchat image bytes");
  const webchatPath = path.join(mediaRoot, "webchat-upload.png");
  writeFileSync(webchatPath, webchatBytes);
  const webchatPrompt = "Remember this webchat upload for later.";
  beforeWrite({
    message: {
      role: "user",
      content: webchatPrompt,
      idempotencyKey: "webchat-run-1:user",
      MediaPath: webchatPath,
      MediaPaths: [webchatPath],
      MediaType: "image/png",
      MediaTypes: ["image/png"],
    },
  }, { sessionKey: "takeover-1" });
  const webchatRuntime = fakeApi(base, { runId: "webchat-run-1" });
  try {
    const webchatObserved = await webchatRuntime.tools
      .get("aetnamem_observe")
      .execute("observe-webchat-runtime-1", {
        text: "The webchat upload is available through trusted structured metadata.",
        modality: "image",
      });
    assert.equal(webchatObserved.details.status, "quarantined");
    assert.equal(webchatObserved.details.success, true);
    assert.equal(webchatObserved.details.provenanceSource, "openclaw-upload");
    assert.equal(
      webchatObserved.details.mediaSha256,
      createHash("sha256").update(webchatBytes).digest("hex"),
    );
  } finally {
    for (const service of webchatRuntime.services) await service.stop?.();
  }

  const forgetArtifact = runtime.tools.get("aetnamem_forget_artifact");
  const artifactForgotten = await forgetArtifact.execute("forget-artifact-1", {
    media_sha256: autoObserved.details.mediaSha256,
    artifact_id: autoObserved.details.artifactId,
  });
  assert.equal(artifactForgotten.details.deleted, true);
  await messageReceived(
    { content: "A later text-only turn", sessionKey: "takeover-1", metadata: {} },
    { sessionKey: "takeover-1" },
  );
  await assert.rejects(
    observe.execute("observe-stale-1", {
      text: "This must not reuse the previous upload.",
      modality: "image",
    }),
    /No exact uploaded-file provenance is bound/,
  );

  await beforePrompt({ prompt: "My favorite color is teal." }, { sessionKey: "capture-1" });
  await agentEnd({ success: true, messages: [] }, { sessionKey: "capture-1" });

  const injected = await beforePrompt(
    { prompt: "What is my favorite color?" },
    { sessionKey: "recall-1" },
  );
  assert.equal(injected.prependContext, undefined);
  assert.ok(injected.appendSystemContext.includes("<user_persona>"));
  assert.ok(injected.appendContext.includes("<relevant_memories>"));
  assert.ok(injected.appendContext.includes("teal"));
  assert.match(injected.appendContext, /\[m:[a-f0-9]{8}\]/);
  assert.doesNotMatch(injected.appendContext, /\[rec_[a-f0-9]+\]/);

  const compatibleSearch = runtime.tools.get("memory_search");
  const searchResult = await compatibleSearch.execute("compat-search-1", {
    query: "favorite color",
    maxResults: 5,
  });
  const searchPayload = JSON.parse(searchResult.content[0].text);
  assert.ok(searchPayload.results.length >= 1);
  assert.match(searchPayload.results[0].path, /^aetnamem:\/\/record\/rec_/);
  assert.equal(typeof searchPayload.results[0].score, "number");

  const compatibleGet = runtime.tools.get("memory_get");
  const getResult = await compatibleGet.execute("compat-get-1", {
    path: searchPayload.results[0].path,
    from: 1,
    lines: 10,
  });
  const getPayload = JSON.parse(getResult.content[0].text);
  assert.ok(getPayload.text.includes("teal"));
  assert.equal(getResult.details.found, true);

  await beforePrompt(
    { prompt: "Actually, use blue as my favorite color going forward." },
    { sessionKey: "capture-2" },
  );
  await agentEnd({ success: true, messages: [] }, { sessionKey: "capture-2" });
  const corrected = await beforePrompt(
    { prompt: "What is my favorite color?" },
    { sessionKey: "recall-2" },
  );
  assert.ok(corrected.appendSystemContext.includes("blue"));
  assert.ok(!corrected.appendSystemContext.includes("teal"));

  const forget = runtime.tools.get("aetnamem_forget");
  const forgotten = await forget.execute("forget-1", {
    utterance: "Forget my favorite color.",
  });
  assert.equal(forgotten.details.deleted, true);
  const afterForget = await beforePrompt(
    { prompt: "What is my favorite color?" },
    { sessionKey: "recall-3" },
  );
  assert.equal(afterForget?.appendSystemContext, undefined);
  assert.equal(afterForget?.appendContext, undefined);

  const cleaned = beforeWrite({
    message: {
      role: "user",
      content:
        "Question\n<user_persona>\n- private\n</user_persona>\n" +
        "<relevant_memories>\n- private\n</relevant_memories>",
    },
  });
  assert.equal(cleaned.message.content, "Question");

  const toolFree = fakeApi({ ...base, tools: { enabled: false } });
  assert.equal(toolFree.tools.size, 0);
  for (const service of toolFree.services) await service.stop?.();

  const legacy = fakeApi({
    ...base,
    dbPath: path.join(dataDir, "legacy.db"),
    commandArgs: ["mcp", "--db", path.join(dataDir, "legacy.db"), "--subject", "legacy"],
    cacheAware: { enabled: false, compactReferences: false },
    tools: { enabled: false },
  });
  const legacyBefore = legacy.hooks.get("before_prompt_build");
  const legacyEnd = legacy.hooks.get("agent_end");
  await legacyBefore({ prompt: "My home city is Sydney." }, { sessionKey: "legacy-capture" });
  await legacyEnd({ success: true, messages: [] }, { sessionKey: "legacy-capture" });
  const legacyInjection = await legacyBefore(
    { prompt: "What is my home city?" },
    { sessionKey: "legacy-recall" },
  );
  assert.ok(legacyInjection.prependContext.includes("Sydney"));
  assert.equal(legacyInjection.appendContext, undefined);
  assert.equal(legacyInjection.appendSystemContext, undefined);
  for (const service of legacy.services) await service.stop?.();

  const takeover = fakeApi({
    ...base,
    takeoverActive: true,
    nativeWorkspace: path.join(dataDir, "openclaw-workspace"),
  });
  const takeoverBefore = takeover.hooks.get("before_prompt_build");
  const guided = await takeoverBefore(
    { prompt: "What do I remember about my favorite color?" },
    { sessionKey: "takeover-1" },
  );
  assert.ok(guided.appendSystemContext.includes("<aetnamem_memory_provider>"));
  assert.ok(guided.appendSystemContext.includes("MEMORY.md and memory/*"));
  assert.ok(guided.appendSystemContext.includes("Use memory_search"));
  assert.ok(guided.appendSystemContext.includes("intentionally unavailable"));
  assert.ok(guided.appendSystemContext.includes("Never call Bash"));
  assert.ok(guided.appendSystemContext.includes("Interpret intent semantically"));
  assert.ok(guided.appendSystemContext.includes("If the user's meaning is both"));
  assert.ok(takeover.tools.has("memory_search"));
  assert.ok(takeover.tools.has("memory_get"));
  assert.ok(takeover.tools.has("memory_remember"));
  assert.equal(typeof takeover.hooks.get("before_model_resolve"), "function");
  await takeover.hooks.get("before_model_resolve")(
    { prompt: "I like blue cars", messages: [], queuedInjections: [] },
    {
      sessionKey: "agent:main:takeover-1",
      sessionId: "takeover-1",
      runId: "run-blue",
    },
  );
  const remembered = await takeover.tools.get("memory_remember").execute(
    "remember-blue",
    { fact: "User likes blue cars." },
  );
  const rememberedPayload = JSON.parse(remembered.content[0].text);
  assert.equal(rememberedPayload.stored, true);
  assert.equal(rememberedPayload.fact, "User likes blue cars.");
  const blueGet = await takeover.tools.get("memory_get").execute(
    "get-blue",
    { path: `aetnamem://record/${rememberedPayload.record_id}` },
  );
  assert.match(blueGet.content[0].text, /User likes blue cars\./);
  const beforeTool = takeover.hooks.get("before_tool_call");
  assert.equal(typeof beforeTool, "function");
  const workspace = path.join(dataDir, "openclaw-workspace");
  const blockedShell = await beforeTool({
    toolName: "Bash",
    params: { command: "sed -n '1,200p' MEMORY.md", cwd: workspace },
  }, {});
  assert.equal(blockedShell.block, true);
  assert.match(blockedShell.blockReason, /memory_remember/);
  const blockedWrite = await beforeTool({
    toolName: "write_file",
    params: { path: path.join(workspace, "memory", "today.md"), content: "note" },
    derivedPaths: [path.join(workspace, "memory", "today.md")],
  }, {});
  assert.equal(blockedWrite.block, true);
  const blockedPatch = await beforeTool({
    toolName: "apply_patch",
    params: { patch: "*** Update File: MEMORY.md\n+preference" },
  }, {});
  assert.equal(blockedPatch.block, true);
  assert.equal(await beforeTool({
    toolName: "Bash",
    params: { command: "pwd && git status", cwd: workspace },
  }, {}), undefined);
  assert.equal(await beforeTool({
    toolName: "write_file",
    params: { path: "/tmp/unrelated/MEMORY.md", content: "project notes" },
    derivedPaths: ["/tmp/unrelated/MEMORY.md"],
  }, {}), undefined);
  for (const service of takeover.services) await service.stop?.();

  const migrationState = path.join(dataDir, "control-plane.json");
  const migrationRoot = path.join(dataDir, "migrations");
  controlCli(
    "shadow",
    "--host",
    "openclaw",
    "--state",
    migrationState,
    "--control-root",
    migrationRoot,
    "--no-configure",
  );
  const controlPlane = fakeApi({
    ...base,
    commandArgs: ["mcp", "--db", path.join(dataDir, "must-not-be-used.db")],
    controlPlane: { enabled: true, statePath: migrationState },
    tools: { enabled: true },
  });
  assert.equal(controlPlane.tools.size, 0);
  const safeBefore = controlPlane.hooks.get("before_prompt_build");
  const safeEnd = controlPlane.hooks.get("agent_end");
  const captureOnly = await safeBefore(
    { prompt: "Remember that my preferred terminal is Ghostty." },
    { sessionKey: "migration-1" },
  );
  assert.equal(captureOnly, undefined);
  await safeEnd({ success: true, messages: [] }, { sessionKey: "migration-1" });
  const migrationStatus = controlCli("status", "--state", migrationState);
  assert.equal(migrationStatus.mode, "shadow");
  assert.equal(migrationStatus.changes_model_context, false);
  for (const service of controlPlane.services) await service.stop?.();

  console.log(
    "hooks: direct engine and fail-closed memory control plane paths verified",
  );
} finally {
  for (const service of runtime.services) await service.stop?.();
  rmSync(dataDir, { recursive: true, force: true });
}
