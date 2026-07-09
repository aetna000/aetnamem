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
  sessionKey?: string;
  sessionId?: string;
}

export interface BeforePromptBuildEvent {
  prompt?: string;
  messages?: unknown[];
}

export interface AgentEndEvent {
  success?: boolean;
  messages?: unknown[];
}

export interface BeforeMessageWriteEvent {
  message: { role?: string; content?: unknown };
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

export interface OpenClawPluginApi {
  pluginConfig?: Record<string, unknown>;
  logger: OpenClawLogger;
  registerTool(spec: OpenClawToolSpec, options?: { name: string }): void;
  on(
    event: "before_prompt_build",
    handler: (
      event: BeforePromptBuildEvent,
      ctx: OpenClawHookCtx,
    ) => Promise<{ prependContext?: string } | void> | { prependContext?: string } | void,
  ): void;
  on(
    event: "agent_end",
    handler: (event: AgentEndEvent, ctx: OpenClawHookCtx) => Promise<void> | void,
  ): void;
  on(
    event: "before_message_write",
    handler: (
      event: BeforeMessageWriteEvent,
    ) => { message: BeforeMessageWriteEvent["message"] } | void,
  ): void;
}
