import jsonPatch, { type Operation } from "fast-json-patch";
import type { ExecutionProcessesState } from "./types";

const { applyPatch } = jsonPatch;

export function applyExecutionProcessPatch(
  current: ExecutionProcessesState | null,
  patches: Operation[],
): ExecutionProcessesState {
  const base = current ?? { execution_processes: {} };
  const result = applyPatch(base, patches, false, false);
  return result.newDocument as ExecutionProcessesState;
}
