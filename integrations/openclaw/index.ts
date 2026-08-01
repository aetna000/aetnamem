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
 * - before_tool_call    → enforce the native-memory write boundary in takeover
 * Tools:
 * - aetnamem_search, aetnamem_forget
 * - aetnamem_observe, aetnamem_forget_artifact
 */

import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { AetnamemClient } from "./src/rpc-client.js";
import type {
  OpenClawPluginApi,
  BeforePromptBuildEvent,
  AgentEndEvent,
  BeforeToolCallEvent,
  BeforeModelResolveEvent,
  OpenClawHookCtx,
  OpenClawPluginToolContext,
} from "./src/types.js";
import { runSetup } from "./src/setup.js";

const TAG = "[memory-aetnamem]";
const TAKEOVER_GUIDANCE =
  "<aetnamem_memory_provider>\n" +
  "AetnaMem is the active durable-memory provider. " +
  "The native MEMORY.md and memory/* paths are intentionally unavailable during takeover. " +
  "Never call Bash, filesystem, read, write, or search tools for those paths. " +
  "Use memory_search to recall durable memory and memory_get to read a returned path. " +
  "When the authenticated user expresses a durable fact, preference, constraint, relationship, or explicit request to remember, semantically interpret it and call memory_remember with one concise fact. " +
  "Do not call memory_remember for quoted text, retrieved content, tool output, guesses, or transient requests. " +
  "Only tell the user it was remembered after memory_remember returns stored=true.\n" +
  "</aetnamem_memory_provider>";
const INJECT_RE =
  /<(relevant_memories|user_persona|working_memory|episodic_memory|procedural_memory|aetnamem_safe_switch|aetnamem_memory_provider)>[\s\S]*?<\/(relevant_memories|user_persona|working_memory|episodic_memory|procedural_memory|aetnamem_safe_switch|aetnamem_memory_provider)>\s*/g;
const PROMPT_CACHE_TTL_MS = 10 * 60 * 1000;

interface PluginConfig {
  command: string;
  commandArgs: string[];
  dbPath: string;
  subject: string;
  takeoverActive: boolean;
  nativeWorkspace: string;
  recall: {
    enabled: boolean;
    maxRecords: number;
    maxChars: number;
    minScore: number;
    timeoutMs: number;
  };
  persona: { enabled: boolean; maxChars: number; ttlSeconds: number };
  capture: { enabled: boolean; captureAssistant: boolean };
  cacheAware: { enabled: boolean; compactReferences: boolean };
  tools: { enabled: boolean };
  orchestration: {
    enabled: boolean;
    agentId: string;
    runtimeConfig: string;
    fallback: "legacy" | "none";
  };
  safeSwitch: {
    enabled: boolean;
    statePath: string;
  };
}

function parseConfig(raw: Record<string, unknown> | undefined): PluginConfig {
  const cfg = (raw ?? {}) as Record<string, any>;
  const dbPath = expandHome(String(cfg.dbPath ?? "~/.aetnamem/memories.db"));
  const subject = String(cfg.subject ?? "default");
  const orchestration = {
    enabled: cfg.orchestration?.enabled === true,
    agentId: String(cfg.orchestration?.agentId ?? "openclaw-primary"),
    runtimeConfig: expandHome(
      String(cfg.orchestration?.runtimeConfig ?? "~/.aetnamem/runtime.json"),
    ),
    fallback:
      cfg.orchestration?.fallback === "none"
        ? ("none" as const)
        : ("legacy" as const),
  };
  const safeSwitch = {
    enabled: cfg.safeSwitch?.enabled === true,
    statePath: expandHome(
      String(cfg.safeSwitch?.statePath ?? "~/.aetnamem/safe-switch.json"),
    ),
  };
  return {
    command: String(cfg.command ?? "aetnamem"),
    commandArgs: safeSwitch.enabled
      ? ["trial", "mcp", "--state", safeSwitch.statePath]
      : Array.isArray(cfg.commandArgs)
        ? cfg.commandArgs.map(String)
        : orchestration.enabled
          ? ["runtime", "mcp", "--config", orchestration.runtimeConfig]
          : ["mcp", "--db", dbPath, "--subject", subject],
    dbPath,
    subject,
    takeoverActive: cfg.takeoverActive === true,
    nativeWorkspace: expandHome(String(cfg.nativeWorkspace ?? "")),
    recall: {
      enabled: cfg.recall?.enabled !== false,
      maxRecords: Number(cfg.recall?.maxRecords ?? 3),
      maxChars: Number(cfg.recall?.maxChars ?? 1200),
      minScore: Number(cfg.recall?.minScore ?? 0.3),
      timeoutMs: Number(cfg.recall?.timeoutMs ?? 4000),
    },
    persona: {
      enabled: cfg.persona?.enabled !== false,
      maxChars: Number(cfg.persona?.maxChars ?? 600),
      ttlSeconds: Number(cfg.persona?.ttlSeconds ?? 300),
    },
    capture: {
      enabled: cfg.capture?.enabled !== false,
      captureAssistant: cfg.capture?.captureAssistant !== false,
    },
    cacheAware: {
      enabled: cfg.cacheAware?.enabled === true,
      compactReferences: cfg.cacheAware?.compactReferences !== false,
    },
    tools: { enabled: cfg.tools?.enabled !== false },
    orchestration,
    safeSwitch,
  };
}

const FILE_TOOL_HINTS = [
  "bash", "shell", "exec", "write", "edit", "patch", "file", "filesystem",
  "read", "delete", "move", "copy", "search",
];

function isFileLikeTool(toolName: string): boolean {
  const normalized = toolName.toLowerCase();
  return FILE_TOOL_HINTS.some((hint) => normalized.includes(hint));
}

function isProtectedNativePath(candidate: string, workspace: string): boolean {
  if (!candidate || !workspace) return false;
  const root = path.resolve(workspace);
  const resolved = path.isAbsolute(candidate)
    ? path.resolve(candidate)
    : path.resolve(root, candidate);
  const memoryFile = path.join(root, "MEMORY.md");
  const memoryDir = path.join(root, "memory");
  return (
    resolved === memoryFile ||
    resolved === memoryDir ||
    resolved.startsWith(memoryDir + path.sep)
  );
}

function collectStrings(value: unknown, output: string[] = []): string[] {
  if (typeof value === "string") output.push(value);
  else if (Array.isArray(value)) {
    for (const item of value) collectStrings(item, output);
  } else if (value && typeof value === "object") {
    for (const item of Object.values(value as Record<string, unknown>)) {
      collectStrings(item, output);
    }
  }
  return output;
}

function commandMentionsNativeMemory(command: string, workspace: string): boolean {
  const normalizedWorkspace = path.resolve(workspace);
  if (command.includes(path.join(normalizedWorkspace, "MEMORY.md"))) return true;
  if (command.includes(path.join(normalizedWorkspace, "memory"))) return true;
  // OpenClaw's agent tools normally execute relative paths from its workspace.
  // Match path tokens, not prose such as "tell me about memory".
  return /(?:^|[\s'"`=;|&:(])(?:\.\/)?MEMORY\.md(?=$|[\s'"`;|&:)])/i.test(command) ||
    /(?:^|[\s'"`=;|&:(])(?:\.\/)?memory(?:\/[^\s'"`;|&)]*)?(?=$|[\s'"`;|&:)])/i.test(command);
}

function touchesNativeMemory(event: BeforeToolCallEvent, workspace: string): boolean {
  if (!workspace) return false;
  if ((event.derivedPaths ?? []).some((candidate) =>
    isProtectedNativePath(candidate, workspace))) return true;
  if (!isFileLikeTool(event.toolName)) return false;

  const params = event.params ?? {};
  const cwdValue = typeof params.cwd === "string" ? params.cwd : workspace;
  const cwd = path.isAbsolute(cwdValue)
    ? path.resolve(cwdValue)
    : path.resolve(workspace, cwdValue);
  const workspaceRoot = path.resolve(workspace);
  const runsInWorkspace = cwd === workspaceRoot || cwd.startsWith(workspaceRoot + path.sep);
  for (const value of collectStrings(params)) {
    if (path.isAbsolute(value) && isProtectedNativePath(value, workspace)) return true;
    if (runsInWorkspace && isProtectedNativePath(value, workspace)) return true;
    if (runsInWorkspace && commandMentionsNativeMemory(value, workspace)) return true;
  }
  return false;
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


function recordIdFromPath(value: string): string | null {
  const prefix = "aetnamem://record/";
  if (!value.startsWith(prefix)) return null;
  const recordId = value.slice(prefix.length).trim();
  return recordId || null;
}

function register(api: OpenClawPluginApi): void {
  const cfg = parseConfig(api.pluginConfig);
  const client = new AetnamemClient({
    command: cfg.command,
    args: cfg.commandArgs,
    log: (message) => api.logger.debug?.(`${TAG} ${message}`),
    logError: (message) => api.logger.warn(`${TAG} ${message}`),
  });
  // Let long-lived hosts close the stdio child during lifecycle shutdown.
  // The client's bounded idle shutdown also covers one-shot local runners.
  api.registerService?.({
    id: "memory-aetnamem-mcp",
    start: () => client.connect(),
    stop: () => client.close(),
  });

  // Per-turn recall state. Semantic admission uses a short-lived SQLite handoff
  // because OpenClaw may run prompt hooks and agent tools in separate runtimes.
  const pendingPrompts = new Map<
    string,
    {
      text: string;
      ts: number;
      runId?: string;
      manifestSha256?: string;
      exposureId?: string;
      injectedRecordIds?: string[];
    }
  >();
  const contextIds = (ctx: OpenClawHookCtx): string[] =>
    [...new Set([ctx.sessionKey, ctx.sessionId].filter(
      (value): value is string => Boolean(value),
    ))];

  const stageInbound = async (
    text: string,
    ctx: OpenClawHookCtx,
  ) => {
    const ids = contextIds(ctx);
    if (!ids.length) return;
    await client.callTool("memory_stage_user_message", {
      message: text.trim(),
      source_aliases: ids,
      run_id: ctx.runId,
      ttl_seconds: 600,
    }, cfg.recall.timeoutMs);
  };

  // OpenClaw documents this as the current prompt before model selection. It
  // is a typed per-turn input surface, not a rendered transcript or history.
  api.on("before_model_resolve", async (event: BeforeModelResolveEvent, ctx) => {
    if (!event.prompt?.trim()) return;
    try {
      await stageInbound(event.prompt, ctx);
    } catch (error) {
      api.logger.warn(
        `${TAG} semantic source handoff unavailable; memory writes will fail closed: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
  });

  api.registerCli?.(
    ({ program }) => {
      const root = program
        .command("aetnamem")
        .description("Configure and inspect AetnaMem for OpenClaw");
      root
        .command("setup")
        .description("Apply safe single-user defaults and enable automatic memory hooks")
        .option("--single-user", "Acknowledge this plugin instance has one memory subject")
        .option("--subject <id>", "Stable single-user memory subject", "you")
        .option("--command <path>", "AetnaMem executable", cfg.command)
        .option("--db-path <path>", "AetnaMem SQLite database", cfg.dbPath)
        .option("--orchestrated", "Use all four AetnaMem memory planes")
        .option(
          "--runtime-config <path>",
          "AetnaMem four-memory runtime configuration",
          cfg.orchestration.runtimeConfig,
        )
        .option("--agent-id <id>", "Stable agent identity", cfg.orchestration.agentId)
        .option("--no-restart", "Do not restart the OpenClaw gateway")
        .action(async (options) => {
          await runSetup({
            subject: String(options.subject),
            command: String(options.command),
            dbPath: String(options.dbPath),
            restart: options.restart !== false,
            orchestrated: options.orchestrated === true,
            runtimeConfig: String(options.runtimeConfig),
            agentId: String(options.agentId),
          });
        });
    },
    { commands: ["aetnamem"] },
  );

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
      {
        session_id: sessionKey,
        max_chars: cfg.persona.maxChars,
        reference_mode: cfg.cacheAware.enabled && cfg.cacheAware.compactReferences
          ? "compact"
          : "full",
      },
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
    const takeoverGuidance = cfg.takeoverActive ? TAKEOVER_GUIDANCE : "";
    pendingPrompts.set(sessionKey, { text: userText, ts: Date.now() });
    sweep();

    if (cfg.safeSwitch.enabled) {
      try {
        const prepared = (await client.callTool(
          "trial_prepare",
          { query: userText, session_id: sessionKey },
          cfg.recall.timeoutMs,
        )) as {
          inject?: boolean;
          context?: string;
          exposure_id?: string;
          mode?: string;
        };
        pendingPrompts.set(sessionKey, {
          text: userText,
          ts: Date.now(),
          exposureId: prepared.exposure_id,
        });
        if (prepared.inject && prepared.context) {
          api.logger.info(
            `${TAG} Safe Switch ${prepared.mode ?? "active"} context exposed`,
          );
          return { appendContext: prepared.context };
        }
        return;
      } catch (error) {
        api.logger.warn(
          `${TAG} Safe Switch failed closed: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
        return;
      }
    }

    if (cfg.orchestration.enabled) {
      try {
        const available = await client.hasTool(
          "memory_prepare_turn",
          cfg.recall.timeoutMs,
        );
        if (!available) {
          throw new Error("connected AetnaMem does not expose memory_prepare_turn");
        }
        const pack = (await client.callTool(
          "memory_prepare_turn",
          {
            query: userText,
            session_id: sessionKey,
            task_state: { goal: userText, phase: "respond" },
          },
          cfg.recall.timeoutMs,
        )) as {
          run_id?: string;
          manifest_sha256?: string;
          stable_context?: string;
          dynamic_context?: string;
          degraded_planes?: string[];
        };
        pendingPrompts.set(sessionKey, {
          text: userText,
          ts: Date.now(),
          runId: pack.run_id,
          manifestSha256: pack.manifest_sha256,
        });
        api.logger.info(
          `${TAG} four-memory pack prepared` +
            (pack.degraded_planes?.length
              ? ` (degraded: ${pack.degraded_planes.join(", ")})`
              : ""),
        );
        const result: { appendSystemContext?: string; appendContext?: string } = {};
        const stableParts = [takeoverGuidance, pack.stable_context].filter(Boolean);
        if (stableParts.length) result.appendSystemContext = stableParts.join("\n\n");
        if (pack.dynamic_context) result.appendContext = pack.dynamic_context;
        if (Object.keys(result).length) return result;
        return;
      } catch (error) {
        api.logger.warn(
          `${TAG} four-memory orchestration unavailable: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
        if (cfg.orchestration.fallback === "none") return;
      }
    }

    if (!cfg.recall.enabled && !cfg.persona.enabled) {
      if (takeoverGuidance) return { appendSystemContext: takeoverGuidance };
      return;
    }

    let persona = "";
    let recall = "";
    try {
      persona = await personaBlock(sessionKey);
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
            reference_mode: cfg.cacheAware.enabled && cfg.cacheAware.compactReferences
              ? "compact"
              : "full",
          },
          cfg.recall.timeoutMs,
        )) as { block?: string; count?: number; record_ids?: string[] };
        if (result?.block) {
          api.logger.info(
            `${TAG} injected ${result.count} memories (${result.block.length} chars)`,
          );
          recall = result.block;
          const current = pendingPrompts.get(sessionKey);
          if (current) {
            pendingPrompts.set(sessionKey, {
              ...current,
              injectedRecordIds: result.record_ids ?? [],
            });
          }
        }
      }
    } catch (error) {
      // Never block the turn on recall problems.
      api.logger.warn(
        `${TAG} auto-recall skipped: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    if (cfg.cacheAware.enabled) {
      const result: { appendSystemContext?: string; appendContext?: string } = {};
      const systemParts = [takeoverGuidance, persona].filter(Boolean);
      if (systemParts.length) result.appendSystemContext = systemParts.join("\n\n");
      if (recall) result.appendContext = recall;
      if (Object.keys(result).length) return result;
      return;
    }
    const parts = [persona, recall].filter(Boolean);
    const result: {
      prependContext?: string;
      appendSystemContext?: string;
    } = {};
    if (parts.length) result.prependContext = parts.join("\n\n") + "\n\n";
    if (takeoverGuidance) result.appendSystemContext = takeoverGuidance;
    if (Object.keys(result).length) return result;
  });

  // ---- enforce takeover: native OpenClaw memory must stay frozen --------
  if (cfg.takeoverActive) {
    api.on("before_tool_call", (event: BeforeToolCallEvent) => {
      if (!touchesNativeMemory(event, cfg.nativeWorkspace)) return;
      const reason =
        "AetnaMem takeover blocked access to OpenClaw's frozen native memory " +
        "(MEMORY.md or memory/*). Use memory_remember for durable user facts, " +
        "and memory_search or memory_get for recall.";
      api.logger.warn(`${TAG} ${reason} Tool: ${event.toolName}`);
      return { block: true, blockReason: reason };
    });
  }

  // ---- auto-capture: user turn through the pipeline, assistant as digest -
  api.on("agent_end", async (event: AgentEndEvent, ctx) => {
    const sessionKey = ctx.sessionKey ?? ctx.sessionId ?? "default-session";

    const cached = pendingPrompts.get(sessionKey);
    pendingPrompts.delete(sessionKey);
    const userText = cached?.text?.replace(INJECT_RE, "").trim();

    try {
      if (cfg.takeoverActive) {
        await client.callTool(
          "memory_clear_user_message",
          { source_aliases: contextIds(ctx) },
          cfg.recall.timeoutMs,
        );
      }
      if (cfg.safeSwitch.enabled) {
        if (cached?.exposureId) {
          await client.callTool(
            "trial_exposure_shown",
            { exposure_id: cached.exposureId },
            cfg.recall.timeoutMs,
          );
        }
        if (event.success !== false) {
          await client.callTool(
            "trial_sync_openclaw_memory",
            {},
            cfg.recall.timeoutMs,
          );
        }
        return;
      }
      if (cfg.takeoverActive && cached?.injectedRecordIds?.length) {
        const messages = Array.isArray(event.messages) ? event.messages : [];
        for (let index = messages.length - 1; index >= 0; index -= 1) {
          const message = messages[index] as { role?: string; content?: unknown };
          if (message?.role !== "assistant") continue;
          const responseText = messageText(message.content);
          if (responseText) {
            await client.callTool("memory_log_action", {
              action_type: "agent.response_after_memory",
              payload: {
                response_sha256: createHash("sha256")
                  .update(responseText, "utf8")
                  .digest("hex"),
                injected_record_ids: cached.injectedRecordIds,
                response_content_stored: false,
                success: event.success !== false,
              },
              session_id: sessionKey,
            });
          }
          break;
        }
      }
      if (
        cfg.capture.enabled &&
        !cfg.takeoverActive &&
        event.success !== false &&
        userText
      ) {
        await client.callTool("memory_capture", {
          role: "user",
          content: userText,
          session_id: sessionKey,
        });
        personaCache = null; // new memory may change the persona
      }
      if (
        cfg.capture.enabled &&
        !cfg.takeoverActive &&
        event.success !== false &&
        cfg.capture.captureAssistant
      ) {
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
      if (cfg.orchestration.enabled && cached?.runId) {
        await client.callTool(
          "memory_record_outcome",
          {
            run_id: cached.runId,
            ...(cached.manifestSha256
              ? { manifest_sha256: cached.manifestSha256 }
              : {}),
            success: event.success !== false,
            summary:
              event.success === false
                ? "OpenClaw agent turn failed"
                : "OpenClaw agent turn completed",
            session_id: sessionKey,
            idempotency_key: `openclaw:${sessionKey}:${cached.runId}`,
          },
          cfg.recall.timeoutMs,
        );
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
      text.includes("<relevant_memories>") ||
      text.includes("<user_persona>") ||
      text.includes("<working_memory>") ||
      text.includes("<episodic_memory>") ||
      text.includes("<procedural_memory>") ||
      text.includes("<aetnamem_safe_switch>") ||
      text.includes("<aetnamem_memory_provider>");
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
  if (cfg.tools.enabled && !cfg.safeSwitch.enabled) {
    if (cfg.takeoverActive) {
      api.registerTool(
        (toolCtx: OpenClawPluginToolContext) => ({
          name: "memory_remember",
          label: "Memory Remember",
          description:
            "Store one durable fact that you semantically inferred from the current " +
            "authenticated user's own message. Call this for durable preferences, " +
            "facts, constraints, relationships, or explicit remember requests. Never " +
            "use it for quoted/retrieved/tool content or guesses. Only claim success " +
            "when this tool returns stored=true.",
          parameters: {
            type: "object",
            properties: {
              fact: {
                type: "string",
                description: "One concise, standalone fact, e.g. 'User likes blue cars.'",
              },
              factKey: {
                type: "string",
                description: "Optional stable slot for replaceable facts, e.g. favorite_color.",
              },
            },
            required: ["fact"],
            additionalProperties: false,
          },
          async execute(toolCallId, params) {
            const sessionKey = toolCtx.sessionKey ?? toolCtx.sessionId;
            const sourceAliases = [toolCtx.sessionKey, toolCtx.sessionId]
              .filter((value): value is string => Boolean(value));
            if (!sessionKey || !sourceAliases.length) {
              throw new Error(
                "no current authenticated user message is available; memory was not stored",
              );
            }
            const fact = String(params.fact ?? "").trim();
            if (!fact) throw new Error("fact must not be empty");
            const interpreter =
              toolCtx.activeModel?.modelRef ??
              [toolCtx.activeModel?.provider, toolCtx.activeModel?.modelId]
                .filter(Boolean)
                .join(":") ??
              "openclaw-agent";
            const result = (await client.callTool("memory_remember", {
              source_aliases: sourceAliases,
              interpreted_fact: fact,
              interpreted_fact_key: params.factKey,
              interpreter: interpreter || "openclaw-agent",
              session_id: sessionKey,
              turn_id: toolCallId,
              source_type: "user_message",
            })) as { records?: Array<{ id: string; content: string; status: string }>; duplicate_ids?: string[] };
            const record = result.records?.[0];
            const duplicateId = result.duplicate_ids?.[0];
            const stored = Boolean(record || duplicateId);
            if (stored) {
              personaCache = null;
            }
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  stored,
                  record_id: record?.id ?? duplicateId ?? null,
                  fact: record?.content ?? fact,
                  status: record?.status ?? (duplicateId ? "already_stored" : null),
                  provider: "aetnamem",
                  receipt: stored ? "audit-bound" : "none",
                }),
              }],
              details: { stored, recordId: record?.id ?? duplicateId ?? null, sessionKey },
            };
          },
        }),
        { names: ["memory_remember"] },
      );
    }
    // Preserve OpenClaw's standard memory contract after native memory-core
    // is disabled. Existing agent prompts and workflows can keep using the
    // same tool names; only the governed storage/retrieval implementation
    // changes underneath them.
    api.registerTool(
      {
        name: "memory_search",
        label: "Memory Search",
        description:
          "Search governed AetnaMem long-term memory. Compatible with OpenClaw's " +
          "standard memory_search contract. The active takeover supports the " +
          "memory corpus; session and wiki corpora must be migrated explicitly.",
        parameters: {
          type: "object",
          properties: {
            query: { type: "string" },
            maxResults: { type: "integer", minimum: 1 },
            minScore: { type: "number" },
            corpus: {
              type: "string",
              enum: ["memory", "wiki", "all", "sessions"],
            },
          },
          required: ["query"],
          additionalProperties: false,
        },
        async execute(toolCallId, params) {
          const corpus = String(params.corpus ?? "memory");
          if (corpus === "wiki" || corpus === "sessions") {
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  results: [],
                  disabled: true,
                  error:
                    `${corpus} corpus is not enabled in this AetnaMem takeover`,
                }),
              }],
              details: { count: 0, corpus, disabled: true },
            };
          }
          const sessionId = `openclaw-memory-search:${toolCallId}`;
          const maxResults = Math.min(
            Math.max(Number(params.maxResults) || 6, 1),
            20,
          );
          const records = (await client.callTool("memory_recall", {
            query: String(params.query ?? ""),
            session_id: sessionId,
            limit: maxResults,
            min_score:
              params.minScore === undefined
                ? cfg.recall.minScore
                : Number(params.minScore),
            include_scores: true,
          })) as Array<{
            id: string;
            content: string;
            score?: number;
            created_at?: string;
            source_type?: string;
          }>;
          const results = records.map((record) => ({
            path: `aetnamem://record/${record.id}`,
            startLine: 1,
            endLine: Math.max(record.content.split("\n").length, 1),
            score: Number(record.score ?? 0),
            snippet: record.content,
            source: "aetnamem",
            corpus: "memory",
            id: record.id,
            sourceType: record.source_type,
            updatedAt: record.created_at,
            citation: `aetnamem:${record.id}`,
          }));
          return {
            content: [{
              type: "text",
              text: JSON.stringify({
                results,
                provider: "aetnamem",
                model: "deterministic-record-rank-v1",
                citations: "auto",
                mode: "governed",
              }),
            }],
            details: { count: results.length, corpus, sessionId },
          };
        },
      },
      { name: "memory_search" },
    );

    api.registerTool(
      {
        name: "memory_get",
        label: "Memory Get",
        description:
          "Read one exact governed AetnaMem record returned by memory_search. " +
          "The read is bounded and added to the AetnaMem audit trail.",
        parameters: {
          type: "object",
          properties: {
            path: { type: "string" },
            from: { type: "integer", minimum: 1 },
            lines: { type: "integer", minimum: 1 },
            corpus: { type: "string", enum: ["memory", "wiki", "all"] },
          },
          required: ["path"],
          additionalProperties: false,
        },
        async execute(toolCallId, params) {
          const lookup = String(params.path ?? "");
          const recordId = recordIdFromPath(lookup);
          if (!recordId) {
            const sessionId = `openclaw-memory-get:${toolCallId}`;
            const sourceResult = (await client.callTool("memory_get_source", {
              path: lookup,
              session_id: sessionId,
            })) as {
              path?: string;
              text?: string;
              source?: Record<string, unknown>;
            } | null;
            if (sourceResult?.text !== undefined) {
              const allLines = sourceResult.text.split("\n");
              const from = Math.max(Number(params.from) || 1, 1);
              const requested = Math.min(
                Math.max(Number(params.lines) || 50, 1),
                200,
              );
              const selected = allLines.slice(from - 1, from - 1 + requested);
              const payload = {
                path: lookup,
                text: selected.join("\n"),
                from,
                lines: selected.length,
                totalLines: allLines.length,
                truncated: from - 1 + selected.length < allLines.length,
                source: "aetnamem-frozen-openclaw",
                provenance: sourceResult.source ?? {},
              };
              return {
                content: [{ type: "text", text: JSON.stringify(payload) }],
                details: { found: true, sessionId },
              };
            }
            return {
              content: [{
                type: "text",
                text: JSON.stringify({
                  path: lookup,
                  text: "",
                  disabled: true,
                  error:
                    "No governed record or frozen OpenClaw memory file matched this path",
                }),
              }],
              details: { found: false },
            };
          }
          const sessionId = `openclaw-memory-get:${toolCallId}`;
          const result = (await client.callTool("memory_get_record", {
            record_id: recordId,
            session_id: sessionId,
          })) as {
            record?: { content?: string };
            source?: Record<string, unknown>;
          } | null;
          const allLines = String(result?.record?.content ?? "").split("\n");
          const from = Math.max(Number(params.from) || 1, 1);
          const requested = Math.min(Math.max(Number(params.lines) || 50, 1), 200);
          const selected = allLines.slice(from - 1, from - 1 + requested);
          const payload = {
            path: lookup,
            text: selected.join("\n"),
            from,
            lines: selected.length,
            totalLines: allLines.length,
            truncated: from - 1 + selected.length < allLines.length,
            source: "aetnamem",
            provenance: result?.source ?? {},
          };
          return {
            content: [{ type: "text", text: JSON.stringify(payload) }],
            details: { found: Boolean(result?.record), sessionId },
          };
        },
      },
      { name: "memory_get" },
    );

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
          if (result.deleted) personaCache = null;
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

    api.registerTool(
      {
        name: "aetnamem_observe",
        label: "Media Observation (aetnamem)",
        description:
          "After analyzing an image, audio clip, video, or document, store one " +
          "typed text observation with its exact-byte SHA-256 provenance. The " +
          "observation is quarantined until explicitly promoted. Confidence is " +
          "evidence only and never grants trust.",
        parameters: {
          type: "object",
          properties: {
            text: { type: "string", description: "What the extractor observed" },
            modality: {
              type: "string",
              enum: ["image", "audio", "video", "document"],
            },
            media_sha256: {
              type: "string",
              description: "SHA-256 of the exact media byte stream",
            },
            host_reference: {
              type: "string",
              description: "Secretless reference controlled by OpenClaw or the user",
            },
            segment: {
              type: "object",
              description: "Optional page, timestamp range, or region label/coordinates",
            },
            extractor: {
              type: "object",
              description:
                "Extractor identity: provider, model, version, and optional model_digest",
            },
            confidence: {
              type: "number",
              description: "Extractor-local score from 0 to 1",
            },
            observed_at: { type: "string", description: "Optional ISO-8601 timestamp" },
          },
          required: [
            "text",
            "modality",
            "media_sha256",
            "host_reference",
            "extractor",
          ],
        },
        async execute(toolCallId, params) {
          const sessionId = `openclaw-tool:${toolCallId}`;
          const result = (await client.callTool("memory_observe", {
            text: String(params.text ?? ""),
            modality: String(params.modality ?? ""),
            media_sha256: String(params.media_sha256 ?? ""),
            host_reference: String(params.host_reference ?? ""),
            segment: params.segment ?? {},
            extractor: params.extractor ?? {},
            confidence: params.confidence,
            observed_at: params.observed_at,
            session_id: sessionId,
            turn_id: toolCallId,
          })) as {
            artifact: { id: string };
            observation: { id: string };
            record: { id: string; status: string };
            duplicate: boolean;
          };
          return {
            content: [
              {
                type: "text",
                text:
                  `Media observation ${result.duplicate ? "already existed" : "stored"} ` +
                  `as quarantined record ${result.record.id}.`,
              },
            ],
            details: {
              artifactId: result.artifact.id,
              observationId: result.observation.id,
              recordId: result.record.id,
              status: result.record.status,
              duplicate: result.duplicate,
              sessionId,
            },
          };
        },
      },
      { name: "aetnamem_observe" },
    );

    api.registerTool(
      {
        name: "aetnamem_forget_artifact",
        label: "Forget Media Artifact (aetnamem)",
        description:
          "Only when the user explicitly requests deletion, purge all AetnaMem " +
          "observations derived from one exact-byte SHA-256. This does not " +
          "delete the host's original file or a re-encoded copy.",
        parameters: {
          type: "object",
          properties: {
            media_sha256: {
              type: "string",
              description: "SHA-256 of the exact media byte stream",
            },
            artifact_id: {
              type: "string",
              description: "Optional artifact id that must match the digest",
            },
          },
          required: ["media_sha256"],
        },
        async execute(toolCallId, params) {
          const sessionId = `openclaw-tool:${toolCallId}`;
          const result = (await client.callTool("memory_forget_artifact", {
            media_sha256: String(params.media_sha256 ?? ""),
            artifact_id: params.artifact_id,
            session_id: sessionId,
            turn_id: toolCallId,
          })) as { deleted: boolean; record_ids: string[]; receipt?: unknown };
          if (result.deleted) personaCache = null;
          const text = result.deleted
            ? `Purged ${result.record_ids.length} derived memorie(s). Receipt: ${JSON.stringify(result.receipt)}`
            : "No active AetnaMem artifact matched that exact digest.";
          return {
            content: [{ type: "text", text }],
            details: { deleted: result.deleted, sessionId },
          };
        },
      },
      { name: "aetnamem_forget_artifact" },
    );
  }

  api.logger.info(
    `${TAG} registered (db=${cfg.dbPath}, subject=${cfg.subject}, ` +
      `recall=${cfg.recall.enabled}, capture=${cfg.capture.enabled}, ` +
      `fourMemory=${cfg.orchestration.enabled}, safeSwitch=${cfg.safeSwitch.enabled})`,
  );
}

export default {
  id: "memory-aetnamem",
  name: "Memory (aetnamem)",
  description: "Automatic, auditable memory for OpenClaw backed by AetnaMem",
  register,
};
