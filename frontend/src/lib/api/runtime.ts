// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, handleResponse } from "./fetch";
import type {
  RuntimeCatalog,
  RuntimeCatalogRequest,
  TestExecutorResponse,
  ValidateRuntimeCatalogResponse,
} from "../types";

export async function getRuntimeCatalog(): Promise<RuntimeCatalog> {
  try {
    const response = await fetch(`${API_BASE}/runtime-catalog`);
    return handleResponse<RuntimeCatalog>(response);
  } catch (err) {
    console.error(`getRuntimeCatalog failed:`, err);
    throw err;
  }
}
export async function updateRuntimeCatalog(catalog: RuntimeCatalog): Promise<RuntimeCatalog> {
  const body: RuntimeCatalogRequest = { catalog };
  const response = await fetch(`${API_BASE}/runtime-catalog`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<RuntimeCatalog>(response);
}
export async function validateRuntimeCatalog(
  catalog: RuntimeCatalog,
): Promise<ValidateRuntimeCatalogResponse> {
  const body: RuntimeCatalogRequest = { catalog };
  const response = await fetch(`${API_BASE}/runtime-catalog/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<ValidateRuntimeCatalogResponse>(response);
}
export interface TestExecutorRequest {
  executor_id: string;
  provider_id?: string | null;
  model_id?: string | null;
  api_endpoint?: string | null;
  api_key?: string | null;
}
export async function testRuntimeExecutor(
  request: TestExecutorRequest,
): Promise<TestExecutorResponse> {
  const response = await fetch(`${API_BASE}/runtime-catalog/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return handleResponse<TestExecutorResponse>(response);
}
