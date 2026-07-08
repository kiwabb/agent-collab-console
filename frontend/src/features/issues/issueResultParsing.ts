import { safeJsonRecord } from "@/lib/utils";

export type AgentResultSection =
  { label: string; kind: "text"; value: string } | { label: string; kind: "list"; value: string[] };

export function parseIssueResultRecord(result: string): Record<string, unknown> | null {
  const trimmed = result.trim();
  if (!(trimmed.startsWith("{") && trimmed.endsWith("}"))) return null;
  return safeJsonRecord(trimmed);
}

export function looksLikeControlPayload(text: string): boolean {
  const record = parseIssueResultRecord(text);
  if (!record) return false;
  if (record["type"] === "system") return true;
  return ["hook_name", "hook_event", "hook_id"].some((key) => key in record);
}

export function extractSummaryFromJsonText(text: string): string {
  const record = parseIssueResultRecord(text);
  if (!record) return "";
  const candidates = [
    record["summary"],
    record["message"],
    record["answer"],
    record["text"],
    record["content"],
    record["error"],
    record["error_message"],
  ];
  for (const candidate of candidates) {
    if (typeof candidate !== "string") continue;
    const cleaned = candidate.trim();
    if (cleaned && !looksLikeControlPayload(cleaned)) return cleaned;
  }
  return "";
}

export function cleanIssueResultText(value: unknown): string {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (!trimmed || looksLikeControlPayload(trimmed)) return "";
  return extractSummaryFromJsonText(trimmed) || trimmed;
}

export function extractAgentResultSections(role: string, result: string): AgentResultSection[] {
  if (!result) return [];
  const payload = parseIssueResultRecord(result);
  if (!payload) {
    return [{ label: "Result", kind: "text", value: result.slice(0, 2000) }];
  }

  const out: AgentResultSection[] = [];
  const text = (key: string, label: string) => {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      out.push({ label, kind: "text", value });
    }
  };
  const list = (key: string, label: string) => {
    const value = payload[key];
    if (!Array.isArray(value) || value.length === 0) return;
    out.push({
      label,
      kind: "list",
      value: value.map((item) => (typeof item === "string" ? item : JSON.stringify(item))),
    });
  };

  switch (role) {
    case "product_manager":
      text("requirement_analysis", "Requirement analysis");
      list("product_goals", "Product goals");
      list("user_stories", "User stories");
      list("acceptance_criteria", "Acceptance criteria");
      list("constraints", "Constraints");
      list("open_questions", "Open questions");
      list("risks", "Risks");
      break;
    case "architect":
      text("architecture_summary", "Architecture summary");
      list("components", "Components");
      list("data_models", "Data models");
      list("interfaces", "Interfaces");
      text("data_flow", "Data flow");
      list("risks", "Risks");
      list("open_questions", "Open questions");
      break;
    case "engineer":
      text("summary", "Summary");
      list("changed_files", "Changed files");
      list("verification_commands", "Verification commands");
      list("risks", "Risks");
      list("qa_notes", "QA notes");
      break;
    case "qa":
      text("final_recommendation", "Final recommendation");
      text("test_scope", "Test scope");
      list("acceptance_coverage", "Acceptance coverage");
      list("commands_run", "Commands run");
      list("bugs_found", "Bugs found");
      list("risks", "Risks");
      list("test_gaps", "Test gaps");
      break;
  }

  const clarificationQuestion = payload["clarification_question"];
  if (typeof clarificationQuestion === "string" && clarificationQuestion.trim()) {
    out.unshift({ label: "Clarification question", kind: "text", value: clarificationQuestion });
  }
  return out;
}

export function deriveAgentResultSummary(role: string, result: string, status: string): string {
  if (!result) return statusHint(status);
  const payload = parseIssueResultRecord(result);

  switch (role) {
    case "product_manager":
      if (payload) {
        const criteria = arrayLen(payload, "acceptance_criteria");
        const goals = arrayLen(payload, "product_goals");
        const reqs = arrayLen(payload, "requirement_pool");
        const parts = [];
        if (criteria)
          parts.push(`${criteria} acceptance ${criteria === 1 ? "criterion" : "criteria"}`);
        if (goals) parts.push(`${goals} goal${goals === 1 ? "" : "s"}`);
        if (reqs) parts.push(`${reqs} req${reqs === 1 ? "" : "s"}`);
        if (parts.length) return parts.join(" · ");
      }
      return shortenResult(result);
    case "architect":
      if (payload) {
        const components = arrayLen(payload, "components");
        const dataModels = arrayLen(payload, "data_models");
        const risks = arrayLen(payload, "risks");
        const parts = [];
        if (components) parts.push(`${components} component${components === 1 ? "" : "s"}`);
        if (dataModels) parts.push(`${dataModels} model${dataModels === 1 ? "" : "s"}`);
        if (risks) parts.push(`${risks} risk${risks === 1 ? "" : "s"}`);
        if (parts.length) return parts.join(" · ");
      }
      return shortenResult(result);
    case "engineer":
      if (payload) {
        const files = arrayLen(payload, "changed_files");
        const resultStatus = String(payload["status"] ?? "");
        if (files || resultStatus) {
          const parts = [];
          if (resultStatus) parts.push(resultStatus);
          if (files) parts.push(`${files} file${files === 1 ? "" : "s"} changed`);
          return parts.join(" · ");
        }
      }
      return shortenResult(result);
    case "qa":
      if (payload) {
        const commands = arrayLen(payload, "commands_run");
        const bugs = arrayLen(payload, "bugs_found");
        const resultStatus = String(payload["status"] ?? "");
        if (resultStatus || commands || bugs) {
          const parts = [];
          if (resultStatus) parts.push(resultStatus);
          if (commands) parts.push(`${commands} cmd${commands === 1 ? "" : "s"}`);
          if (bugs) parts.push(`${bugs} bug${bugs === 1 ? "" : "s"}`);
          return parts.join(" · ");
        }
      }
      return shortenResult(result);
    default:
      return shortenResult(result);
  }
}

function arrayLen(payload: Record<string, unknown>, key: string): number {
  const value = payload[key];
  return Array.isArray(value) ? value.length : 0;
}

function shortenResult(value: string): string {
  return value.length <= 80 ? value : `${value.slice(0, 77)}…`;
}

function statusHint(status: string): string {
  switch (status) {
    case "pending":
      return "Queued";
    case "running":
    case "responding":
      return "Working…";
    case "awaiting_review":
      return "Awaiting clarification";
    case "failed":
      return "Failed";
    default:
      return status || "—";
  }
}
