/**
 * memory-aetnamem: auditable memory plugin for OpenClaw.
 *
 * A thin shell over the aetnamem engine (Python, spawned as an MCP child
 * process over stdio). The plugin adds automatic memory ergonomics —
 * auto-recall injection, auto-capture, agent-callable search — while every
 * policy decision (quarantine, supersession, deletion, receipts, audit
 * chain) stays server-side in the engine, where a prompt-injected agent
 * cannot reach it.
 *
 * Hooks:
 * - before_prompt_build → memory_recall_block (bounded, audited injection)
 * - agent_end           → memory_capture for the user turn + assistant digest
 * - before_message_write → strip injected <relevant_memories> from history
 * Tools:
 * - aetnamem_search, aetnamem_forget
 */

import os from "node:os";
import path from "node:path";
import { AetnamemClient } from "./src/rpc-client.js";
import type {
  OpenClawPluginApi,
  BeforePromptBuildEvent,
  AgentEndEvent,
} from "./src/types.js";

const TAG = "[memory-aetnamem]";
const INJECT_RE =
  /<(relevant_memories|user_persona)>[\s\S]*?<\/(relevant_memories|user_persona)>\s*/g;
const PROMPT_CACHE_TTL_MS = 10 * 60 * 1000;

interface PluginConfig {
  command: string;
  commandArgs: string[];
  dbPath: string;
  subject: string;
  recall: {
    enabled: boolean;
    maxRecords: number;
    maxChars: number;
    minScore: number;
    timeoutMs: number;
  };
  persona: { enabled: boolean; maxChars: number; ttlSeconds: number };
  capture: { enabled: boolean; captureAssistant: boolean };
}

function parseConfig(raw: Record<string, unknown> | undefined): PluginConfig {
  const cfg = (raw ?? {}) as Record<string, any>;
  const dbPath = expandHome(String(cfg.dbPath ?? "~/.aetnamem/memories.db"));
  const subject = String(cfg.subject ?? "default");
  return {
    command: String(cfg.command ?? "aetna000"),
    commandArgs: Array.isArray(cfg.commandArgs)
      ? cfg.commandArgs.map(String)
      : ["mcp", "--db", dbPath, "--subject", subject],
    dbPath,
    subject,
    recall: {
      enabled: cfg.recall?.enabled !== false,
      maxRecords: Number(cfg.recall?.maxRecords ?? 5),
      maxChars: Number(cfg.recall?.maxChars ?? 2000),
      minScore: Number(cfg.recall?.minScore ?? 0.3),
      timeoutMs: Number(cfg.recall?.timeoutMs ?? 4000),
    },
    persona: {
      enabled: cfg.persona?.enabled !== false,
      maxChars: Number(cfg.persona?.maxChars ?? 1200),
      ttlSeconds: Number(cfg.persona?.ttlSeconds ?? 300),
    },
    capture: {
      enabled: cfg.capture?.enabled !== false,
      captureAssistant: cfg.capture?.captureAssistant !== false,
    },
  };
}

function expandHome(filePath: string): string {
  return filePath.startsWith("~")
    ? path.join(os.homedir(), filePath.slice(1))
    : filePath;
}

/** Extract plain text from an OpenClaw message content shape. */
function messageText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) =>
        part && typeof part === "object" && (part as any).type === "text"
          ? String((part as any).text ?? "")
          : "",
      )
      .join("");
  }
  return "";
}

export default function register(api: OpenClawPluginApi): void {
  const cfg = parseConfig(api.pluginConfig);
  const client = new AetnamemClient({
    command: cfg.command,
    args: cfg.commandArgs,
    log: (message) => api.logger.debug?.(`${TAG} ${message}`),
    logError: (message) => api.logger.warn(`${TAG} ${message}`),
  });

  // Clean user prompts cached per session so agent_end captures the turn
  // without the injected memory block.
  const pendingPrompts = new Map<string, { text: string; ts: number }>();

  // L3 persona cache: rebuilt on TTL expiry and invalidated when capture
  // writes new memory, so the snapshot never lags a correction.
  let personaCache: { block: string; ts: number } | null = null;

  const sweep = () => {
    const now = Date.now();
    for (const [key, value] of pendingPrompts) {
      if (now - value.ts > PROMPT_CACHE_TTL_MS) pendingPrompts.delete(key);
    }
  };

  async function personaBlock(sessionKey: string): Promise<string> {
    if (!cfg.persona.enabled) return "";
    const now = Date.now();
    if (personaCache && now - personaCache.ts < cfg.persona.ttlSeconds * 1000) {
      return personaCache.block;
    }
    const result = (await client.callTool(
      "memory_persona",
      { session_id: sessionKey, max_chars: cfg.persona.maxChars },
      cfg.recall.timeoutMs,
    )) as { block?: string };
    personaCache = { block: result?.block ?? "", ts: now };
    return personaCache.block;
  }

  // ---- auto-recall: persona + bounded, audited recall injection ---------
  api.on("before_prompt_build", async (event: BeforePromptBuildEvent, ctx) => {
    const userText = event.prompt;
    if (!userText) return;
    const sessionKey = ctx.sessionKey ?? ctx.sessionId ?? "default-session";
    pendingPrompts.set(sessionKey, { text: userText, ts: Date.now() });
    sweep();
    if (!cfg.recall.enabled && !cfg.persona.enabled) return;

    const parts: string[] = [];
    try {
      const persona = await personaBlock(sessionKey);
      if (persona) parts.push(persona);
    } catch (error) {
      api.logger.warn(
        `${TAG} persona skipped: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    try {
      if (cfg.recall.enabled) {
        const result = (await client.callTool(
          "memory_recall_block",
          {
            query: userText,
            session_id: sessionKey,
            max_records: cfg.recall.maxRecords,
            max_chars: cfg.recall.maxChars,
            min_score: cfg.recall.minScore,
          },
          cfg.recall.timeoutMs,
        )) as { block?: string; count?: number };
        if (result?.block) {
          api.logger.info(
            `${TAG} injected ${result.count} memories (${result.block.length} chars)`,
          );
          parts.push(result.block);
        }
      }
    } catch (error) {
      // Never block the turn on recall problems.
      api.logger.warn(
        `${TAG} auto-recall skipped: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    if (parts.length) return { prependContext: parts.join("\n\n") + "\n\n" };
  });

  // ---- auto-capture: user turn through the pipeline, assistant as digest -
  api.on("agent_end", async (event: AgentEndEvent, ctx) => {
    if (!cfg.capture.enabled || event.success === false) return;
    const sessionKey = ctx.sessionKey ?? ctx.sessionId ?? "default-session";

    const cached = pendingPrompts.get(sessionKey);
    pendingPrompts.delete(sessionKey);
    const userText = cached?.text?.replace(INJECT_RE, "").trim();

    try {
      if (userText) {
        await client.callTool("memory_capture", {
          role: "user",
          content: userText,
          session_id: sessionKey,
        });
        personaCache = null; // new memory may change the persona
      }
      if (cfg.capture.captureAssistant) {
        const messages = Array.isArray(event.messages) ? event.messages : [];
        for (let index = messages.length - 1; index >= 0; index -= 1) {
          const message = messages[index] as { role?: string; content?: unknown };
          if (message?.role === "assistant") {
            const text = messageText(message.content);
            if (text) {
              await client.callTool("memory_capture", {
                role: "assistant",
                content: text,
                session_id: sessionKey,
              });
            }
            break;
          }
        }
      }
    } catch (error) {
      api.logger.warn(
        `${TAG} auto-capture failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  });

  // ---- keep injected blocks out of persisted history ---------------------
  api.on("before_message_write", (event) => {
    const message = event.message;
    if (message.role !== "user") return;
    const hasInjection = (text: string) =>
      text.includes("<relevant_memories>") || text.includes("<user_persona>");
    if (typeof message.content === "string") {
      if (!hasInjection(message.content)) return;
      const cleaned = message.content.replace(INJECT_RE, "").trim();
      return { message: { ...message, content: cleaned } };
    }
    if (Array.isArray(message.content)) {
      let changed = false;
      const parts = (message.content as Array<Record<string, unknown>>).map((part) => {
        if (part.type !== "text" || typeof part.text !== "string") return part;
        if (!hasInjection(part.text)) return part;
        changed = true;
        return { ...part, text: part.text.replace(INJECT_RE, "").trim() };
      });
      if (changed) return { message: { ...message, content: parts } };
    }
  });

  // ---- agent-callable tools ----------------------------------------------
  api.registerTool(
    {
      name: "aetnamem_search",
      label: "Memory Search (aetnamem)",
      description:
        "Search the user's long-term auditable memory. Use when you need " +
        "preferences, facts, or context from previous conversations that " +
        "were not auto-injected.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "What to recall about the user" },
          limit: { type: "number", description: "Max results (default 5)" },
        },
        required: ["query"],
      },
      async execute(toolCallId, params) {
        const sessionId = `openclaw-tool:${toolCallId}`;
        const records = (await client.callTool("memory_recall", {
          query: String(params.query ?? ""),
          session_id: sessionId,
          limit: Math.min(Math.max(Number(params.limit) || 5, 1), 20),
        })) as Array<{ id: string; content: string }>;
        const text = records.length
          ? records.map((record) => `- [${record.id}] ${record.content}`).join("\n")
          : "No matching memories.";
        return {
          content: [{ type: "text", text }],
          details: { count: records.length, sessionId },
        };
      },
    },
    { name: "aetnamem_search" },
  );

  api.registerTool(
    {
      name: "aetnamem_forget",
      label: "Memory Forget (aetnamem)",
      description:
        "Delete the user's memories matching their request — only call when " +
        "the user explicitly asks to forget something. Deletion purges " +
        "content and returns a verifiable receipt; report the purged count " +
        "back to the user.",
      parameters: {
        type: "object",
        properties: {
          utterance: {
            type: "string",
            description: 'The user\'s words, e.g. "Forget my backup email."',
          },
        },
        required: ["utterance"],
      },
      async execute(toolCallId, params) {
        const sessionId = `openclaw-tool:${toolCallId}`;
        const result = (await client.callTool("memory_forget", {
          utterance: String(params.utterance ?? ""),
          session_id: sessionId,
          turn_id: toolCallId,
        })) as { deleted: boolean; record_ids: string[]; receipt?: unknown };
        const text = result.deleted
          ? `Deleted ${result.record_ids.length} memorie(s). Receipt: ${JSON.stringify(result.receipt)}`
          : "No matching memories found to delete.";
        return {
          content: [{ type: "text", text }],
          details: { deleted: result.deleted, sessionId },
        };
      },
    },
    { name: "aetnamem_forget" },
  );

  api.logger.info(
    `${TAG} registered (db=${cfg.dbPath}, subject=${cfg.subject}, ` +
      `recall=${cfg.recall.enabled}, capture=${cfg.capture.enabled})`,
  );
}
