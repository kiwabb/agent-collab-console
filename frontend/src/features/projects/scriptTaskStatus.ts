const TERMINAL_TASK_STATUSES = new Set([
  "done",
  "completed",
  "failed",
  "error",
  "cancelled",
  "canceled",
  "killed",
]);

export function describeScriptTaskTerminalStatus(status: string | null | undefined): {
  terminal: boolean;
  success: boolean;
} {
  const normalized = String(status || "").toLowerCase();
  return {
    terminal: TERMINAL_TASK_STATUSES.has(normalized),
    success: normalized === "done" || normalized === "completed",
  };
}
