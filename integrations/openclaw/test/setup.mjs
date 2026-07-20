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
assert.equal(writes.length, 3);
assert.equal(writes[1][0], "plugins.entries.memory-aetnamem.hooks.allowConversationAccess");
const config = JSON.parse(writes[2][1]);
assert.equal(config.subject, "alice");
assert.equal(config.recall.maxRecords, 3);
assert.equal(config.recall.maxChars, 1200);
assert.equal(config.persona.maxChars, 600);

const calls = [];
await runSetup(options, {
  invocation: { command: "openclaw-test", prefix: [] },
  runner(command, args) {
    calls.push([command, args]);
    return { status: 0 };
  },
});
assert.equal(calls.length, 4);
assert.deepEqual(calls.at(-1), ["openclaw-test", ["gateway", "restart"]]);
assert.ok(calls[0][1].includes("--strict-json"));

console.log("setup: safe OpenClaw configuration contract verified");
