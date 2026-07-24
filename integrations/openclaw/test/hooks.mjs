#!/usr/bin/env node
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import plugin from "../dist/index.js";


function fakeApi(config) {
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
    registerTool(spec) { tools.set(spec.name, spec); },
    registerService(service) { services.push(service); },
  };
  plugin.register(api);
  return { hooks, tools, services, logs };
}


const dataDir = mkdtempSync(path.join(tmpdir(), "aetnamem-hooks-"));
const dbPath = path.join(dataDir, "memory.db");
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

const runtime = fakeApi(base);
const beforePrompt = runtime.hooks.get("before_prompt_build");
const agentEnd = runtime.hooks.get("agent_end");
const beforeWrite = runtime.hooks.get("before_message_write");

try {
  assert.equal(runtime.tools.size, 2);

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

  const fourDb = path.join(dataDir, "four-memory.db");
  const fourConfigPath = path.join(dataDir, "runtime.json");
  writeFileSync(
    fourConfigPath,
    JSON.stringify({
      format: "aetnamem-runtime-config-v1",
      preset: "starter",
      db_path: fourDb,
      scope: { subject_id: "four-user", agent_id: "openclaw-primary" },
      budgets: {
        total_chars: 4200,
        working_chars: 700,
        semantic_chars: 1800,
        episodic_chars: 900,
        procedural_chars: 800,
      },
      planes: {
        working: { enabled: true },
        semantic: { enabled: true, max_records: 3, min_score: 0.3 },
        episodic: { enabled: true, max_outcomes: 3 },
        procedural: { enabled: true, skill_paths: [] },
      },
      failure_policy: "degrade",
    }),
  );
  const fourMemory = fakeApi({
    ...base,
    dbPath: fourDb,
    subject: "four-user",
    commandArgs: ["runtime", "mcp", "--config", fourConfigPath],
    orchestration: {
      enabled: true,
      agentId: "openclaw-primary",
      runtimeConfig: fourConfigPath,
      fallback: "legacy",
    },
  });
  const fourBefore = fourMemory.hooks.get("before_prompt_build");
  const fourEnd = fourMemory.hooks.get("agent_end");
  const firstPack = await fourBefore(
    { prompt: "My deployment region is Sydney." },
    { sessionKey: "four-1" },
  );
  assert.ok(
    firstPack?.appendContext?.includes("<working_memory>"),
    fourMemory.logs.join("\n"),
  );
  await fourEnd({ success: true, messages: [] }, { sessionKey: "four-1" });
  const recalledPack = await fourBefore(
    { prompt: "What is my deployment region?" },
    { sessionKey: "four-2" },
  );
  assert.ok(
    `${recalledPack.appendSystemContext ?? ""}${recalledPack.appendContext ?? ""}`.includes(
      "Sydney",
    ),
  );
  await fourEnd({ success: true, messages: [] }, { sessionKey: "four-2" });
  for (const service of fourMemory.services) await service.stop?.();

  console.log(
    "hooks: legacy compatibility and opt-in four-memory orchestration verified",
  );
} finally {
  for (const service of runtime.services) await service.stop?.();
  rmSync(dataDir, { recursive: true, force: true });
}
