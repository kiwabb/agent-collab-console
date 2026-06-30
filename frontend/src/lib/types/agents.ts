// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

export interface Agent {
  id: string;
  workspace_id: string | null;
  name: string;
  role_key: string;
  description: string | null;
  system_prompt_template: string;
  input_schema: Array<Record<string, unknown>>;
  output_schema: Record<string, unknown>;
  default_executor: string | null;
  default_provider: string | null;
  default_model: string | null;
  artifact_subdir: string | null;
  persist_kind: string | null;
  agent_tier: "managed" | "specialist" | "custom";
  triggers_replan_on_done: boolean;
  triggers_replan_on_fail: boolean;
  is_builtin: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateAgentRequest {
  name: string;
  role_key: string;
  description?: string | null;
  system_prompt_template: string;
  workspace_id?: string | null;
  input_schema?: Array<Record<string, unknown>>;
  output_schema?: Record<string, unknown>;
  default_executor?: string | null;
  default_provider?: string | null;
  default_model?: string | null;
  artifact_subdir?: string | null;
  persist_kind?: string | null;
  agent_tier?: "managed" | "specialist" | "custom";
  triggers_replan_on_done?: boolean;
  triggers_replan_on_fail?: boolean;
}

export interface UpdateAgentRequest {
  name?: string;
  description?: string | null;
  system_prompt_template?: string;
  input_schema?: Array<Record<string, unknown>>;
  output_schema?: Record<string, unknown>;
  default_executor?: string | null;
  default_provider?: string | null;
  default_model?: string | null;
  artifact_subdir?: string | null;
  persist_kind?: string | null;
  triggers_replan_on_done?: boolean;
  triggers_replan_on_fail?: boolean;
}
