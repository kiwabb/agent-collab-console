// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

export interface RuntimeModelConfig {
  id: string;
  label: string;
  enabled: boolean;
}

export interface RuntimeProviderConfig {
  id: string;
  label: string;
  enabled: boolean;
  models: RuntimeModelConfig[];
  default_model_id: string | null;
  command_template?: string | null;
  env_template?: Record<string, string> | null;
}

export interface AcpRuntimeConfig {
  command: string;
  args: string[];
  env_allowlist: string[];
  permission_timeout_s: number;
  model_config_id: string | null;
}

export interface RuntimeExecutorConfig {
  id: string;
  label: string;
  enabled: boolean;
  executor_type: "claude" | "codex" | "acp";
  api_endpoint?: string | null;
  api_key?: string | null;
  api_key_configured?: boolean;
  default_model?: string | null;
  protocol?: "anthropic" | "openai";
  providers: RuntimeProviderConfig[];
  default_provider_id: string | null;
  acp?: AcpRuntimeConfig | null;
}

export interface ConductorLLMConfig {
  executor_id?: string | null;
  model?: string | null;
  max_tokens?: number;
  timeout_s?: number;
  // Language for the conductor's user-facing output. "auto" matches the issue's
  // language; otherwise a UI locale code ("zh-CN" / "en-US") synced from Settings.
  output_language?: string;
}

export interface RuntimeCatalog {
  executors: RuntimeExecutorConfig[];
  conductor_llm?: ConductorLLMConfig;
}

export interface RuntimeCatalogRequest {
  catalog: RuntimeCatalog;
}

export interface ValidateRuntimeCatalogResponse {
  valid: boolean;
  error?: string;
}

export interface TestExecutorResponse {
  success: boolean;
  latency_ms?: number;
  error?: string;
  mode?: string;
  detail?: string;
}
