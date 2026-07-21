/**
 * Newline-delimited JSON-RPC 2.0 client for the `aetnamem mcp` stdio server.
 *
 * The child process is spawned lazily on first call, the MCP initialize
 * handshake runs once, and calls are matched to responses by request id.
 * If the child dies it is respawned on the next call.
 */

import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface, type Interface } from "node:readline";

export interface AetnamemClientOptions {
  command: string;
  args: string[];
  log?: (message: string) => void;
  logError?: (message: string) => void;
  defaultTimeoutMs?: number;
  idleTimeoutMs?: number;
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class AetnamemClient {
  private child: ChildProcessWithoutNullStreams | null = null;
  private reader: Interface | null = null;
  private pending = new Map<number, Pending>();
  private nextId = 1;
  private initialized: Promise<void> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly options: AetnamemClientOptions) {}

  /** Call an MCP tool; returns the parsed JSON payload of the text block. */
  async callTool(
    name: string,
    args: Record<string, unknown>,
    timeoutMs?: number,
  ): Promise<unknown> {
    try {
      this.cancelIdleClose();
      await this.ensureInitialized();
      const result = (await this.request(
        "tools/call",
        { name, arguments: args },
        timeoutMs,
      )) as {
        isError?: boolean;
        content?: Array<{ type: string; text?: string }>;
      };
      const text = result?.content?.[0]?.text ?? "";
      if (result?.isError) {
        throw new Error(`aetnamem tool ${name} failed: ${text}`);
      }
      try {
        return JSON.parse(text);
      } catch {
        return text;
      }
    } finally {
      this.scheduleIdleClose();
    }
  }

  close(): void {
    this.cancelIdleClose();
    if (this.child) {
      this.child.stdin.end();
      this.child.kill();
    }
    this.teardown(new Error("client closed"));
  }

  private cancelIdleClose(): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
  }

  private scheduleIdleClose(): void {
    this.cancelIdleClose();
    const timeout = this.options.idleTimeoutMs ?? 250;
    this.idleTimer = setTimeout(() => this.close(), timeout);
  }

  private async ensureInitialized(): Promise<void> {
    if (!this.child || this.child.exitCode !== null) {
      this.startChild();
      this.initialized = this.handshake();
    }
    await this.initialized;
  }

  private startChild(): void {
    const { command, args } = this.options;
    this.options.log?.(`[aetnamem] spawning: ${command} ${args.join(" ")}`);
    const child = spawn(command, args, { stdio: ["pipe", "pipe", "pipe"] });
    this.child = child;

    this.reader = createInterface({ input: child.stdout });
    this.reader.on("line", (line) => this.onLine(line));

    child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString().trim();
      if (text) this.options.logError?.(`[aetnamem stderr] ${text}`);
    });
    child.on("exit", (code) => {
      this.options.logError?.(`[aetnamem] server exited (code ${code})`);
      this.teardown(new Error(`aetnamem server exited (code ${code})`));
    });
    child.on("error", (error) => {
      this.options.logError?.(`[aetnamem] spawn failed: ${error.message}`);
      this.teardown(error instanceof Error ? error : new Error(String(error)));
    });
  }

  private async handshake(): Promise<void> {
    await this.request("initialize", {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "openclaw-memory-aetnamem", version: "0.2.4" },
    });
    this.notify("notifications/initialized", {});
  }

  private request(
    method: string,
    params: Record<string, unknown>,
    timeoutMs?: number,
  ): Promise<unknown> {
    const child = this.child;
    if (!child) return Promise.reject(new Error("aetnamem server not running"));
    const id = this.nextId++;
    const timeout = timeoutMs ?? this.options.defaultTimeoutMs ?? 10_000;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`aetnamem ${method} timed out after ${timeout}ms`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    });
  }

  private notify(method: string, params: Record<string, unknown>): void {
    this.child?.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n");
  }

  private onLine(line: string): void {
    if (!line.trim()) return;
    let message: {
      id?: number;
      result?: unknown;
      error?: { code: number; message: string };
    };
    try {
      message = JSON.parse(line);
    } catch {
      this.options.logError?.(`[aetnamem] unparseable line: ${line.slice(0, 200)}`);
      return;
    }
    if (message.id === undefined) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.error) {
      pending.reject(new Error(`aetnamem rpc error ${message.error.code}: ${message.error.message}`));
    } else {
      pending.resolve(message.result);
    }
  }

  private teardown(error: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
    this.reader?.close();
    this.reader = null;
    this.child = null;
    this.initialized = null;
  }
}
