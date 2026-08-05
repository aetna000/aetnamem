/**
 * Minimal structural types for the OpenClaw plugin API surface this plugin
 * uses. Kept local (instead of importing "openclaw/plugin-sdk/core") so the
 * plugin builds without the SDK on the compile path; the shapes match the
 * hook/tool contracts observed in OpenClaw's plugin SDK.
 */

export interface OpenClawLogger {
  debug?: (message: string) => void;
  info: (message: string) => void;
  warn: (message: string) => void;
  error: (message: string) => void;
}

export interface OpenClawHookCtx {
  runId?: string;
  sessionKey?: string;
  sessionId?: string;
}

export interface BeforePromptBuildEvent {
  prompt?: string;
  messages?: unknown[];
}

export interface AgentEndEvent {
  runId?: string;
  success: boolean;
  error?: string;
  durationMs?: number;
  messages: unknown[];
}

export interface BeforeModelResolveEvent {
  prompt: string;
  attachments?: Array<{
    kind: "image" | "video" | "audio" | "document" | "other";
    mimeType?: string;
  }>;
}

export interface MessageReceivedEvent {
  content: string;
  sessionKey?: string;
  runId?: string;
  metadata?: {
    mediaPath?: string;
    mediaPaths?: string[];
    mediaType?: string;
    mediaTypes?: string[];
    [key: string]: unknown;
  };
}

export interface OpenClawPluginToolContext {
  agentId?: string;
  runId?: string;
  sessionKey?: string;
  sessionId?: string;
  senderIsOwner?: boolean;
  activeModel?: { provider?: string; modelId?: string; modelRef?: string };
}

export interface BeforeMessageWriteEvent {
  message: {
    role?: string;
    content?: unknown;
    idempotencyKey?: string;
    MediaPath?: string;
    MediaPaths?: string[];
    MediaType?: string;
    MediaTypes?: string[];
    mediaPath?: string;
    mediaPaths?: string[];
    mediaType?: string;
    mediaTypes?: string[];
  };
}

export interface BeforeToolCallEvent {
  toolName: string;
  params: Record<string, unknown>;
  derivedPaths?: readonly string[];
  runId?: string;
  toolCallId?: string;
  toolKind?: string;
}

export interface AfterToolCallEvent {
  toolName: string;
  params: Record<string, unknown>;
  runId?: string;
  toolCallId?: string;
  result?: unknown;
  error?: string;
  durationMs?: number;
}

export interface LlmInputEvent {
  runId: string;
  sessionId: string;
  provider: string;
  model: string;
  systemPrompt?: string;
  prompt: string;
  historyMessages: unknown[];
  imagesCount: number;
  tools?: unknown[];
}

export interface LlmOutputEvent {
  runId: string;
  sessionId: string;
  provider: string;
  model: string;
  resolvedRef?: string;
  harnessId?: string;
  assistantTexts: string[];
  usage?: Record<string, number | undefined>;
  reasoningEffort?: string;
  fastMode?: boolean;
}

export interface BeforeToolCallResult {
  block?: boolean;
  blockReason?: string;
}

export interface ToolResultBlock {
  content: Array<{ type: "text"; text: string }>;
  details?: Record<string, unknown>;
}

export interface OpenClawToolSpec {
  name: string;
  label?: string;
  description: string;
  parameters: Record<string, unknown>;
  execute(toolCallId: string, params: Record<string, unknown>): Promise<ToolResultBlock>;
}

export interface CliCommand {
  command(name: string): CliCommand;
  description(text: string): CliCommand;
  option(flags: string, description: string, defaultValue?: unknown): CliCommand;
  action(handler: (options: Record<string, unknown>) => Promise<void> | void): CliCommand;
}

export interface OpenClawPluginApi {
  pluginConfig?: Record<string, unknown>;
  logger: OpenClawLogger;
  registerCli?: (
    registrar: (context: { program: CliCommand }) => void,
    options?: { commands: string[] },
  ) => void;
  registerTool(
    spec: OpenClawToolSpec | ((ctx: OpenClawPluginToolContext) => OpenClawToolSpec),
    options?: { name?: string; names?: string[] },
  ): void;
  on(
    event: "message_received",
    handler: (
      event: MessageReceivedEvent,
      ctx: OpenClawHookCtx,
    ) => Promise<void> | void,
  ): void;
  on(
    event: "before_model_resolve",
    handler: (
      event: BeforeModelResolveEvent,
      ctx: OpenClawHookCtx,
    ) => Promise<void> | void,
  ): void;
  on(
    event: "llm_input",
    handler: (event: LlmInputEvent, ctx: OpenClawHookCtx) => Promise<void> | void,
  ): void;
  on(
    event: "llm_output",
    handler: (event: LlmOutputEvent, ctx: OpenClawHookCtx) => Promise<void> | void,
  ): void;
  registerService?: (service: {
    id: string;
    start: () => void | Promise<void>;
    stop?: () => void | Promise<void>;
  }) => void;
  on(
    event: "before_prompt_build",
    handler: (
      event: BeforePromptBuildEvent,
      ctx: OpenClawHookCtx,
    ) =>
      | Promise<{
          prependContext?: string;
          appendContext?: string;
          appendSystemContext?: string;
        } | void>
      | {
          prependContext?: string;
          appendContext?: string;
          appendSystemContext?: string;
        }
      | void,
  ): void;
  on(
    event: "agent_end",
    handler: (event: AgentEndEvent, ctx: OpenClawHookCtx) => Promise<void> | void,
  ): void;
  on(
    event: "before_message_write",
    handler: (
      event: BeforeMessageWriteEvent,
      ctx: OpenClawHookCtx,
    ) => { message: BeforeMessageWriteEvent["message"] } | void,
  ): void;
  on(
    event: "before_tool_call",
    handler: (
      event: BeforeToolCallEvent,
      ctx: OpenClawHookCtx,
    ) => BeforeToolCallResult | void | Promise<BeforeToolCallResult | void>,
  ): void;
  on(
    event: "after_tool_call",
    handler: (event: AfterToolCallEvent, ctx: OpenClawHookCtx) => Promise<void> | void,
  ): void;
}
