// Typed API client. Split by domain (frontend lib split). This file is now a
// re-export aggregator so existing `from "@/lib/api"` imports resolve to the
// same surface. Per-domain wrappers live in ./api/<domain>.ts; shared fetch
// infrastructure lives in ./api/fetch.ts.

export { API_BASE, WS_BASE, formatApiErrorDetail, dedupedFetch, handleResponse } from "./api/fetch";
export * from "./api/health";
export * from "./api/workspaces";
export * from "./api/projects";
export * from "./api/stats";
export * from "./api/benchmarks";
export * from "./api/audit";
export * from "./api/issues";
export * from "./api/tasks";
export * from "./api/runtime";
export * from "./api/approvals";
export * from "./api/agents";
export * from "./api/conductors";
export * from "./api/knowledge";
export * from "./api/skills";
export * from "./api/prototypes";
