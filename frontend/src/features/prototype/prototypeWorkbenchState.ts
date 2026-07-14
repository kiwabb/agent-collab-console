import type { PrototypeGenerationRun } from "@/lib/types";

export function shouldOpenPrototypeWorkbench(
  run: PrototypeGenerationRun | null,
  navigationRunId: string | null,
): run is PrototypeGenerationRun {
  return run !== null && run.id === navigationRunId && run.status === "completed";
}
