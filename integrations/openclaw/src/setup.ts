import { accessSync, constants } from "node:fs";
import { delimiter, isAbsolute } from "node:path";
import { spawnSync } from "node:child_process";

export interface SetupOptions {
  subject: string;
  command: string;
  dbPath: string;
  restart: boolean;
  orchestrated?: boolean;
  runtimeConfig?: string;
  agentId?: string;
}

interface Invocation {
  command: string;
  prefix: string[];
}

type Runner = (command: string, args: string[]) => { status: number | null };

function executableExists(command: string): boolean {
  if (command.includes("/") || isAbsolute(command)) {
    try {
      accessSync(command, constants.X_OK);
      return true;
    } catch {
      return false;
    }
  }
  return (process.env.PATH ?? "")
    .split(delimiter)
    .some((entry) => {
      try {
        accessSync(`${entry}/${command}`, constants.X_OK);
        return true;
      } catch {
        return false;
      }
    });
}

function currentOpenClawInvocation(): Invocation {
  const script = process.argv[1];
  if (script && /node(?:\.exe)?$/i.test(process.execPath)) {
    return { command: process.execPath, prefix: [script] };
  }
  return { command: process.argv[0] || "openclaw", prefix: [] };
}

export function setupWrites(options: SetupOptions): Array<[string, string, boolean]> {
  const config = {
    command: options.command,
    dbPath: options.dbPath,
    subject: options.subject,
    recall: {
      enabled: true,
      maxRecords: 3,
      maxChars: 1200,
      minScore: 0.3,
      timeoutMs: 3000,
    },
    persona: { enabled: true, maxChars: 600, ttlSeconds: 300 },
    capture: { enabled: true, captureAssistant: true },
    cacheAware: { enabled: true, compactReferences: true },
    tools: { enabled: true },
    orchestration: {
      enabled: options.orchestrated === true,
      agentId: options.agentId ?? "openclaw-primary",
      runtimeConfig: options.runtimeConfig ?? "~/.aetnamem/runtime.json",
      fallback: "legacy",
    },
  };
  return [
    ["plugins.entries.memory-aetnamem.enabled", "true", true],
    ["plugins.entries.memory-aetnamem.hooks.allowConversationAccess", "true", true],
    [
      "plugins.entries.memory-aetnamem.config.command",
      JSON.stringify(config.command),
      true,
    ],
    [
      "plugins.entries.memory-aetnamem.config.dbPath",
      JSON.stringify(config.dbPath),
      true,
    ],
    [
      "plugins.entries.memory-aetnamem.config.subject",
      JSON.stringify(config.subject),
      true,
    ],
    [
      "plugins.entries.memory-aetnamem.config.recall",
      JSON.stringify(config.recall),
      true,
    ],
    [
      "plugins.entries.memory-aetnamem.config.persona",
      JSON.stringify(config.persona),
      true,
    ],
    [
      "plugins.entries.memory-aetnamem.config.capture",
      JSON.stringify(config.capture),
      true,
    ],
    [
      "plugins.entries.memory-aetnamem.config.cacheAware",
      JSON.stringify(config.cacheAware),
      true,
    ],
    [
      "plugins.entries.memory-aetnamem.config.tools",
      JSON.stringify(config.tools),
      true,
    ],
    [
      "plugins.entries.memory-aetnamem.config.orchestration",
      JSON.stringify(config.orchestration),
      true,
    ],
  ];
}

export async function runSetup(
  options: SetupOptions,
  dependencies: { runner?: Runner; invocation?: Invocation } = {},
): Promise<void> {
  if (!options.subject.trim()) throw new Error("--subject must not be empty");
  if (!executableExists(options.command)) {
    throw new Error(
      `AetnaMem executable not found: ${options.command}. Run: python3 -m pip install --upgrade aetnamem`,
    );
  }

  const invocation = dependencies.invocation ?? currentOpenClawInvocation();
  const runner: Runner = dependencies.runner ?? ((command, args) =>
    spawnSync(command, args, { stdio: "inherit" }));

  for (const [key, value, strictJson] of setupWrites(options)) {
    const args = [...invocation.prefix, "config", "set", key, value];
    if (strictJson) args.push("--strict-json");
    const result = runner(invocation.command, args);
    if (result.status !== 0) {
      throw new Error(`OpenClaw rejected configuration key: ${key}`);
    }
  }

  if (options.restart) {
    const result = runner(invocation.command, [...invocation.prefix, "gateway", "restart"]);
    if (result.status !== 0) {
      throw new Error("Configuration was saved, but the OpenClaw gateway restart failed");
    }
  }

  process.stdout.write(
    `AetnaMem is configured with ${options.orchestrated ? "four-memory orchestration" : "bounded auto-recall"} and capture. ` +
      "Existing MEMORY.md files were not changed; reduce duplicate native memory only after verifying recall.\n",
  );
}
