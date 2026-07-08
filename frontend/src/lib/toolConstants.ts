import type { ToolCategory } from "./types";
import { isRecord } from "./utils";

export const READ_TOOL_NAMES = new Set(["read", "read_file", "readfile", "file_read"]);
export const EDIT_TOOL_NAMES = new Set([
  "edit",
  "edit_file",
  "editfile",
  "write",
  "write_file",
  "writefile",
  "write_to_file",
  "replace_string",
  "file_edit",
  "file_write",
  "notebookedit",
  "create_file",
  "multiedit",
]);
export const BASH_TOOL_NAMES = new Set([
  "bash",
  "shell",
  "terminal",
  "run_terminal_cmd",
  "execute_command",
  "shell_command",
  "run_command",
  "exec",
  "exec_command",
]);
export const SEARCH_TOOL_NAMES = new Set(["grep", "glob", "search", "find", "ripgrep", "rg"]);
export const WEB_TOOL_NAMES = new Set([
  "webfetch",
  "websearch",
  "web_fetch",
  "web_search",
  "fetch",
  "http",
]);
export const TODO_TOOL_NAMES = new Set(["todowrite", "todo_write", "todoread", "todo_read"]);

export function isMcpTool(name: string): boolean {
  const n = name.toLowerCase();
  return n.includes("mcp__") || n.startsWith("mcp_");
}

export function isReadTool(name: string): boolean {
  const n = name.toLowerCase();
  return READ_TOOL_NAMES.has(n) || (n.includes("read") && !n.includes("todo"));
}

export function isEditTool(name: string): boolean {
  const n = name.toLowerCase();
  if (EDIT_TOOL_NAMES.has(n)) return true;
  if (TODO_TOOL_NAMES.has(n)) return false;
  return n.includes("edit") || n.includes("write");
}

export function isBashTool(name: string): boolean {
  const n = name.toLowerCase();
  return (
    BASH_TOOL_NAMES.has(n) || n.includes("bash") || n.includes("shell") || n.includes("terminal")
  );
}

export function isSearchTool(name: string): boolean {
  const n = name.toLowerCase();
  return (
    SEARCH_TOOL_NAMES.has(n) ||
    n.includes("grep") ||
    n.includes("glob") ||
    (n.includes("search") && !n.includes("web"))
  );
}

export function isWebTool(name: string): boolean {
  const n = name.toLowerCase();
  return WEB_TOOL_NAMES.has(n) || n.includes("web") || n.includes("fetch");
}

export function isTodoTool(name: string): boolean {
  return TODO_TOOL_NAMES.has(name.toLowerCase()) || name.toLowerCase().includes("todo");
}

export function classifyTool(toolName: string, itemType?: string | null): ToolCategory {
  const t = (itemType ?? "").toLowerCase().replace(/-/g, "_");
  if (t === "command_execution") return "bash";
  if (t === "file_change") return "fileChange";
  if (t === "mcp_tool_call") return "mcp";
  if (t === "web_search") return "web";

  const n = toolName.toLowerCase();
  if (isBashTool(n)) return "bash";
  if (isTodoTool(n)) return "todo";
  if (isReadTool(n)) return "read";
  if (isEditTool(n)) return "edit";
  if (isSearchTool(n)) return "search";
  if (isWebTool(n)) return "web";
  if (isMcpTool(n)) return "mcp";
  return "other";
}

const FAILED_REGEX = /(fail|error|cancel(?:led)?|abort|timeout|timed[_ -]?out)/;
const COMPLETED_REGEX = /(complete|completed|success|succeed(?:ed)?|done|finish(?:ed)?)/;
const PROCESSING_REGEX = /(pending|running|processing|started|in[_ -]?progress|queued)/;

export function resolveToolStatus(
  status: string | undefined | null,
  hasOutput: boolean,
  isError?: boolean,
): "running" | "success" | "failed" {
  if (isError) return "failed";
  const normalized = (status ?? "").toLowerCase();
  if (FAILED_REGEX.test(normalized)) return "failed";
  if (COMPLETED_REGEX.test(normalized)) return "success";
  if (PROCESSING_REGEX.test(normalized)) return "running";
  return hasOutput ? "success" : "running";
}

export function getFileName(path?: string | null): string {
  if (!path) return "";
  const normalized = String(path).replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts.length ? (parts[parts.length - 1] ?? path) : path;
}

export function truncateText(text: string, maxLength = 80): string {
  if (!text || text.length <= maxLength) return text;
  return text.slice(0, maxLength) + "…";
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
}

export function pickString(source: Record<string, unknown> | null, keys: string[]): string {
  if (!source) return "";
  for (const key of keys) {
    const v = source[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

export const PATH_KEYS = [
  "file_path",
  "filePath",
  "filepath",
  "path",
  "target_file",
  "targetFile",
  "filename",
  "file",
];
export const OLD_STRING_KEYS = ["old_string", "oldString"];
export const NEW_STRING_KEYS = ["new_string", "newString"];
export const CONTENT_KEYS = ["content", "new_content", "newContent"];
export const COMMAND_KEYS = ["command", "cmd", "script", "shell_command", "bash"];
export const PATTERN_KEYS = ["pattern", "query", "regex", "search"];

export function normalizeCommand(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!Array.isArray(value)) return "";
  return value
    .filter((v): v is string => typeof v === "string")
    .map((v) => v.trim())
    .filter(Boolean)
    .join(" ");
}

export function extractCommand(args: Record<string, unknown> | null): string {
  if (!args) return "";
  for (const key of COMMAND_KEYS) {
    const v = args[key];
    const c = normalizeCommand(v);
    if (c) return c;
  }
  return "";
}

export function cleanShellWrapper(command: string): string {
  if (!command) return "";
  const trimmed = command.trim();
  const shellMatch = trimmed.match(
    /^(?:\/\S+\/)?(?:bash|zsh|sh|fish)(?:\.exe)?\s+-(?:l?c)\s+(['"])([\s\S]+)\1$/,
  );
  const inner = shellMatch ? (shellMatch[2] ?? trimmed) : trimmed;
  const cdMatch = inner.match(/^\s*cd\s+[^&;]+(?:\s*&&\s*|\s*;\s*)([\s\S]+)$/i);
  return (cdMatch ? (cdMatch[1] ?? inner) : inner).trim();
}
