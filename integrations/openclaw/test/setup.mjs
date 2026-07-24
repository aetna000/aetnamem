#!/usr/bin/env node
import assert from "node:assert/strict";
import { setupWrites, runSetup } from "../dist/src/setup.js";

const options = {
  subject: "alice",
  command: process.execPath,
  dbPath: "/tmp/aetnamem-test.db",
  restart: true,
};

const writes = setupWrites(options);
assert.equal(writes.length, 11);
assert.equal(writes[1][0], "plugins.entries.memory-aetnamem.hooks.allowConversationAccess");
const configured = Object.fromEntries(
  writes.slice(2).map(([key, value]) => [key.split(".").at(-1), JSON.parse(value)]),
);
assert.equal(configured.subject, "alice");
assert.equal(configured.recall.maxRecords, 3);
assert.equal(configured.recall.maxChars, 1200);
assert.equal(configured.persona.maxChars, 600);
assert.equal(configured.cacheAware.enabled, true);
assert.equal(configured.cacheAware.compactReferences, true);
assert.equal(configured.tools.enabled, true);
assert.equal(configured.orchestration.enabled, false);

const calls = [];
await runSetup(options, {
  invocation: { command: "openclaw-test", prefix: [] },
  runner(command, args) {
    calls.push([command, args]);
    return { status: 0 };
  },
});
assert.equal(calls.length, 12);
assert.deepEqual(calls.at(-1), ["openclaw-test", ["gateway", "restart"]]);
assert.ok(calls[0][1].includes("--strict-json"));

console.log("setup: safe OpenClaw configuration contract verified");
