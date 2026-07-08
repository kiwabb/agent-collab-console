// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequest } from "./fetch";
import type {
  RuntimeCatalog,
  RuntimeCatalogRequest,
  TestExecutorResponse,
  ValidateRuntimeCatalogResponse,
} from "../types";

export async function getRuntimeCatalog(): Promise<RuntimeCatalog> {
  try {
    return await apiRequest<RuntimeCatalog>(`${API_BASE}/runtime-catalog`);
  } catch (err) {
    console.error(`getRuntimeCatalog failed:`, err);
    throw err;
  }
}
export async function updateRuntimeCatalog(catalog: RuntimeCatalog): Promise<RuntimeCatalog> {
  const body: RuntimeCatalogRequest = { catalog };
  return apiJsonRequest<RuntimeCatalog>(`${API_BASE}/runtime-catalog`, "PUT", body);
}
export async function validateRuntimeCatalog(
  catalog: RuntimeCatalog,
): Promise<ValidateRuntimeCatalogResponse> {
  const body: RuntimeCatalogRequest = { catalog };
  return apiJsonRequest<ValidateRuntimeCatalogResponse>(
    `${API_BASE}/runtime-catalog/validate`,
    "POST",
    body,
  );
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
  return apiJsonRequest<TestExecutorResponse>(`${API_BASE}/runtime-catalog/test`, "POST", request);
}
export async function testRuntimeExecutorCli(
  request: TestExecutorRequest,
): Promise<TestExecutorResponse> {
  return apiJsonRequest<TestExecutorResponse>(
    `${API_BASE}/runtime-catalog/test-cli`,
    "POST",
    request,
  );
}
