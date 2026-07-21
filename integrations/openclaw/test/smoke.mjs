#!/usr/bin/env node
/**
 * Protocol-level smoke test for the OpenClaw plugin's server contract.
 *
 * Spawns the real `aetnamem mcp` server and drives the exact tool calls the
 * plugin makes (memory_recall_block, memory_capture, memory_recall,
 * memory_forget), asserting the payload shapes index.ts depends on.
 *
 * Usage: node test/smoke.mjs [--command /path/to/aetnamem]
 */

import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import assert from "node:assert/strict";

const commandIndex = process.argv.indexOf("--command");
const command = commandIndex > -1 ? process.argv[commandIndex + 1] : "aetnamem";

const dataDir = mkdtempSync(path.join(tmpdir(), "aetnamem-smoke-"));
const dbPath = path.join(dataDir, "mem.db");

const child = spawn(
  command,
  ["mcp", "--db", dbPath, "--subject", "smoke-user"],
  { stdio: ["pipe", "pipe", "inherit"], env: process.env },
);

const reader = createInterface({ input: child.stdout });
const pending = new Map();
let nextId = 1;

reader.on("line", (line) => {
  if (!line.trim()) return;
  const message = JSON.parse(line);
  if (message.id !== undefined && pending.has(message.id)) {
    const { resolve, timer } = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(timer);
    resolve(message);
  }
});

function request(method, params) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      if (pending.delete(id)) reject(new Error(`${method} timed out`));
    }, 10_000);
    pending.set(id, { resolve, timer });
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  });
}

async function callTool(name, args) {
  const response = await request("tools/call", { name, arguments: args });
  assert.equal(response.error, undefined, `${name}: ${JSON.stringify(response.error)}`);
  assert.equal(response.result.isError, false, `${name} returned isError`);
  return JSON.parse(response.result.content[0].text);
}

try {
  const init = await request("initialize", { protocolVersion: "2025-06-18" });
  assert.equal(init.result.serverInfo.name, "aetnamem");
  child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");

  // agent_end capture path: user turn runs the pipeline
  const captured = await callTool("memory_capture", {
    role: "user",
    content: "My favorite color is teal.",
    session_id: "s1",
  });
  assert.equal(captured.kind, "remembered");
  assert.equal(captured.records[0].status, "active");

  // assistant capture is digest-only
  const assistantLog = await callTool("memory_capture", {
    role: "assistant",
    content: "Noted! Teal it is.",
    session_id: "s1",
  });
  assert.equal(assistantLog.kind, "logged");

  // before_prompt_build path: bounded injection block
  const block = await callTool("memory_recall_block", {
    query: "What is my favorite color?",
    session_id: "s2",
    max_records: 5,
    max_chars: 2000,
    min_score: 0.3,
  });
  assert.equal(block.count, 1);
  assert.ok(block.block.startsWith("<relevant_memories>"));
  assert.ok(block.block.includes("teal"));

  const compactBlock = await callTool("memory_recall_block", {
    query: "What is my favorite color?",
    session_id: "s2-compact",
    reference_mode: "compact",
  });
  assert.ok(compactBlock.block.includes(`[m:${captured.records[0].id.slice(4, 12)}]`));
  assert.ok(!compactBlock.block.includes(captured.records[0].id));

  // L3 persona snapshot: derived live, provenance ids on every line
  const persona = await callTool("memory_persona", { max_chars: 1200 });
  assert.equal(persona.count, 1);
  assert.ok(persona.block.startsWith("<user_persona>"));
  assert.ok(persona.block.includes("teal"));
  assert.ok(persona.block.includes(captured.records[0].id));

  const compactPersona = await callTool("memory_persona", {
    max_chars: 1200,
    reference_mode: "compact",
  });
  assert.ok(compactPersona.block.includes(`[m:${captured.records[0].id.slice(4, 12)}]`));
  assert.ok(!compactPersona.block.includes(captured.records[0].id));

  // unrelated query must inject nothing (no leak via priors)
  const empty = await callTool("memory_recall_block", {
    query: "zzz unrelated",
    session_id: "s2",
  });
  assert.equal(empty.count, 0);
  assert.equal(empty.block, "");

  // aetnamem_search tool path
  const records = await callTool("memory_recall", { query: "favorite color", limit: 5 });
  assert.ok(Array.isArray(records) && records.length === 1);

  // aetnamem_forget tool path: receipt comes back
  const forgotten = await callTool("memory_forget", {
    utterance: "Forget my favorite color.",
  });
  assert.equal(forgotten.deleted, true);
  assert.equal(forgotten.receipt.format, "aetnamem-deletion-receipt-v1");

  console.log("smoke: all OpenClaw plugin server contracts verified");
} finally {
  child.stdin.end();
  child.kill();
  rmSync(dataDir, { recursive: true, force: true });
}
