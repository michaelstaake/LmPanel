import { UserUpdateResponse } from "./records";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export const BACKEND_UNAVAILABLE_EVENT = "lmpanel:backend-unavailable";
export const BACKEND_UNAVAILABLE_MESSAGE = "Connection lost. Please refresh the page. If this problem persists, check server and container status.";

let backendUnavailableLocked = false;

type ApiErrorPayload = {
  detail?: string | { msg?: string } | Array<{ msg?: string }>;
};

type UploadProgress = {
  loaded: number;
  total: number;
};

function notifyBackendUnavailable() {
  backendUnavailableLocked = true;
  window.dispatchEvent(new Event(BACKEND_UNAVAILABLE_EVENT));
}

function buildBackendUnavailableError(): Error {
  return new Error(BACKEND_UNAVAILABLE_MESSAGE);
}

export function isBackendUnavailableLocked(): boolean {
  return backendUnavailableLocked;
}

export function resolveApiUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

function ensureBackendAvailable() {
  if (backendUnavailableLocked) {
    throw buildBackendUnavailableError();
  }
}

export function isBackendUnavailableResponse(status: number): boolean {
  return status === 0 || status === 502 || status === 503 || status === 504;
}

export function handleBackendUnavailableError(error: unknown): never {
  if (error instanceof DOMException && error.name === "AbortError") {
    throw error;
  }

  if (error instanceof TypeError) {
    notifyBackendUnavailable();
    throw buildBackendUnavailableError();
  }

  throw error;
}

function buildApiError(status: number, statusText: string, bodyText: string): Error {
  try {
    const payload = JSON.parse(bodyText) as ApiErrorPayload;
    if (typeof payload.detail === "string" && payload.detail) {
      return new Error(payload.detail);
    }
    if (Array.isArray(payload.detail) && payload.detail.length > 0 && payload.detail[0]?.msg) {
      return new Error(payload.detail[0].msg);
    }
    if (payload.detail && typeof payload.detail === "object" && "msg" in payload.detail && typeof payload.detail.msg === "string") {
      return new Error(payload.detail.msg);
    }
  } catch {
    // Fall through to status/body based error handling when the response is not JSON.
  }

  const text = bodyText.trim();
  if (text && !text.startsWith("<!DOCTYPE") && !text.startsWith("<html")) {
    return new Error(`Request failed: ${status} (${text.slice(0, 220)})`);
  }

  const readableStatusText = statusText ? ` ${statusText}` : "";
  return new Error(`Request failed: ${status}${readableStatusText}`);
}

async function parseError(response: Response): Promise<Error> {
  const bodyText = await response.text();
  return buildApiError(response.status, response.statusText, bodyText);
}

export async function apiGet<T>(path: string, token?: string): Promise<T> {
  ensureBackendAvailable();

  let response: Response;

  try {
    response = await fetch(resolveApiUrl(path), {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined
    });
  } catch (error) {
    handleBackendUnavailableError(error);
  }

  if (isBackendUnavailableResponse(response.status)) {
    notifyBackendUnavailable();
    throw buildBackendUnavailableError();
  }

  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json() as Promise<T>;
}

export async function apiPost<TRequest, TResponse>(path: string, payload: TRequest, token?: string): Promise<TResponse> {
  ensureBackendAvailable();

  const headers: Record<string, string> = {
    "Content-Type": "application/json"
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;

  try {
    response = await fetch(resolveApiUrl(path), {
      method: "POST",
      headers,
      body: JSON.stringify(payload)
    });
  } catch (error) {
    handleBackendUnavailableError(error);
  }

  if (isBackendUnavailableResponse(response.status)) {
    notifyBackendUnavailable();
    throw buildBackendUnavailableError();
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json() as Promise<TResponse>;
}

export async function apiPatch<TRequest, TResponse>(path: string, payload: TRequest, token?: string): Promise<TResponse> {
  ensureBackendAvailable();

  const headers: Record<string, string> = {
    "Content-Type": "application/json"
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;

  try {
    response = await fetch(resolveApiUrl(path), {
      method: "PATCH",
      headers,
      body: JSON.stringify(payload)
    });
  } catch (error) {
    handleBackendUnavailableError(error);
  }

  if (isBackendUnavailableResponse(response.status)) {
    notifyBackendUnavailable();
    throw buildBackendUnavailableError();
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json() as Promise<TResponse>;
}

export async function apiDelete<TResponse>(path: string, token?: string): Promise<TResponse> {
  ensureBackendAvailable();

  let response: Response;

  try {
    response = await fetch(resolveApiUrl(path), {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined
    });
  } catch (error) {
    handleBackendUnavailableError(error);
  }

  if (isBackendUnavailableResponse(response.status)) {
    notifyBackendUnavailable();
    throw buildBackendUnavailableError();
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json() as Promise<TResponse>;
}

export async function apiPostForm<TResponse>(path: string, formData: FormData, token?: string): Promise<TResponse> {
  ensureBackendAvailable();

  let response: Response;

  try {
    response = await fetch(resolveApiUrl(path), {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: formData
    });
  } catch (error) {
    handleBackendUnavailableError(error);
  }

  if (isBackendUnavailableResponse(response.status)) {
    notifyBackendUnavailable();
    throw buildBackendUnavailableError();
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json() as Promise<TResponse>;
}

export async function apiPostFormWithProgress<TResponse>(
  path: string,
  formData: FormData,
  token?: string,
  onProgress?: (progress: UploadProgress) => void,
  onUploadComplete?: () => void,
): Promise<TResponse> {
  ensureBackendAvailable();

  return new Promise<TResponse>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", resolveApiUrl(path));
    request.responseType = "text";

    if (token) {
      request.setRequestHeader("Authorization", `Bearer ${token}`);
    }

    request.upload.addEventListener("progress", (event) => {
      if (!onProgress) {
        return;
      }

      onProgress({
        loaded: event.loaded,
        total: event.lengthComputable ? event.total : 0,
      });
    });

    request.upload.addEventListener("load", () => {
      onUploadComplete?.();
    });

    request.addEventListener("load", () => {
      const responseText = request.responseText ?? "";

      if (isBackendUnavailableResponse(request.status)) {
        notifyBackendUnavailable();
        reject(buildBackendUnavailableError());
        return;
      }

      if (request.status < 200 || request.status >= 300) {
        reject(buildApiError(request.status, request.statusText, responseText));
        return;
      }

      try {
        resolve(JSON.parse(responseText) as TResponse);
      } catch {
        reject(new Error("Request succeeded but returned invalid JSON"));
      }
    });

    request.addEventListener("error", () => {
      notifyBackendUnavailable();
      reject(buildBackendUnavailableError());
    });

    request.addEventListener("abort", () => {
      reject(new Error("Upload aborted"));
    });

    request.send(formData);
  });
}

export async function fetchWebSearchProviders<T>(token?: string): Promise<T> {
  return apiGet<T>("/api/admin/web-search/providers", token);
}

export async function updateWebSearchProvider<TRequest, TResponse>(
  providerType: string,
  payload: TRequest,
  token?: string,
): Promise<TResponse> {
  return apiPatch<TRequest, TResponse>(`/api/admin/web-search/providers/${providerType}`, payload, token);
}

export async function fetchActiveWebSearchProvider<T>(token?: string): Promise<T> {
  return apiGet<T>("/api/admin/web-search/active", token);
}

export async function setActiveWebSearchProvider<T>(providerType: string | null, token?: string): Promise<T> {
  return apiPatch<{ provider_type: string | null }, T>("/api/admin/web-search/active", { provider_type: providerType }, token);
}

export async function fetchSslStatus<T>(token?: string): Promise<T> {
  return apiGet<T>("/api/admin/ssl/status", token);
}

export async function updateSslSettings<TRequest, TResponse>(payload: TRequest, token?: string): Promise<TResponse> {
  return apiPatch<TRequest, TResponse>("/api/admin/ssl/settings", payload, token);
}

export async function obtainLetsEncryptCertificate<T>(token?: string): Promise<T> {
  return apiPost<Record<string, never>, T>("/api/admin/ssl/letsencrypt", {}, token);
}

export async function renewLetsEncryptCertificate<T>(token?: string): Promise<T> {
  return apiPost<Record<string, never>, T>("/api/admin/ssl/renew", {}, token);
}

// Knowledge Base API functions
export async function fetchKbDocuments<T>(token?: string, categoryId?: number): Promise<T> {
  const params = categoryId !== undefined ? `?category_id=${categoryId}` : "";
  return apiGet<T>(`/api/knowledge-base/documents${params}`, token);
}

export async function createKbDocument<TRequest, TResponse>(payload: TRequest, token?: string): Promise<TResponse> {
  return apiPost<TRequest, TResponse>("/api/knowledge-base/documents", payload, token);
}

export async function updateKbDocument<TRequest, TResponse>(docId: number, payload: TRequest, token?: string): Promise<TResponse> {
  return apiPatch<TRequest, TResponse>(`/api/knowledge-base/documents/${docId}`, payload, token);
}

export async function deleteKbDocument<TResponse>(docId: number, token?: string): Promise<TResponse> {
  return apiDelete<TResponse>(`/api/knowledge-base/documents/${docId}`, token);
}

export async function fetchKbRagContext<T>(query: string, token?: string, categoryId?: number): Promise<T> {
  const params = categoryId !== undefined ? `&category_id=${categoryId}` : "";
  return apiGet<T>(`/api/knowledge-base/rag-context?query=${encodeURIComponent(query)}${params}`, token);
}

// Knowledge Base Category API functions
export async function fetchKbCategories<T>(token?: string): Promise<T> {
  return apiGet<T>("/api/knowledge-base/categories", token);
}

export async function createKbCategory<TRequest, TResponse>(payload: TRequest, token?: string): Promise<TResponse> {
  return apiPost<TRequest, TResponse>("/api/knowledge-base/categories", payload, token);
}

export async function updateKbCategory<TRequest, TResponse>(catId: number, payload: TRequest, token?: string): Promise<TResponse> {
  return apiPatch<TRequest, TResponse>(`/api/knowledge-base/categories/${catId}`, payload, token);
}

export async function deleteKbCategory<TResponse>(catId: number, token?: string): Promise<TResponse> {
  return apiDelete<TResponse>(`/api/knowledge-base/categories/${catId}`, token);
}

export type UpdateCheckRecord = {
  latest_commit: string;
  latest_version: string;
  update_available: boolean;
};

export async function checkForUpdates(token?: string): Promise<UpdateCheckRecord> {
  return apiGet<UpdateCheckRecord>("/api/admin/updates/check", token);
}

export type RunningTaskRecord = {
  task_id: string;
  task_type: string;
  description: string;
  status: string;
  progress: number;
  metadata: Record<string, string | number | boolean | null>;
  created_at: number;
  error: string | null;
};

export async function fetchRunningTasks(token?: string): Promise<RunningTaskRecord[]> {
  return apiGet<RunningTaskRecord[]>("/api/tasks", token);
}

export async function cancelRunningTask(taskId: string, token?: string): Promise<{ status: string; message: string }> {
  return apiDelete<{ status: string; message: string }>(`/api/tasks/${taskId}`, token);
}

export type TaskStatusResponse = {
  task_id: string;
  task_type: string;
  description: string;
  status: string;
  progress: number;
  metadata: Record<string, string | number | boolean | null>;
  created_at: number;
  error: string | null;
};

export async function fetchTaskStatus(taskId: string, token?: string): Promise<TaskStatusResponse> {
  const tasks = await apiGet<TaskStatusResponse[]>("/api/tasks", token);
  return tasks.find(t => t.task_id === taskId) || null as unknown as TaskStatusResponse;
}

export type V1ModelEntry = {
  id: string;
  object: string;
  created: number;
  owned_by: string;
  description?: string;
  context_length?: number;
  tool_calling_enabled?: boolean;
  discourage_thinking?: boolean;
  default_thinking_enabled?: boolean;
  thinking_capability?: string;
  thinking_controllable?: boolean;
  vision_enabled?: boolean;
  web_search_enabled?: boolean;
  web_search_available?: boolean;
  rag_enabled?: boolean;
};

export type V1ModelsResponse = {
  object: string;
  data: V1ModelEntry[];
};

export async function fetchV1Models(token?: string): Promise<V1ModelsResponse> {
  return apiGet<V1ModelsResponse>("/v1/models", token);
}

export async function updateUserEmail(userId: number, email: string, token?: string): Promise<UserUpdateResponse> {
  return apiPatch<{ email: string }, UserUpdateResponse>(`/api/admin/users/${userId}/email`, { email }, token);
}

export async function updateUserPassword(userId: number, password: string, token?: string): Promise<UserUpdateResponse> {
  return apiPatch<{ password: string }, UserUpdateResponse>(`/api/admin/users/${userId}/password`, { password }, token);
}

export async function toggleUserActive(userId: number, token?: string): Promise<UserUpdateResponse> {
  return apiPatch<Record<string, never>, UserUpdateResponse>(`/api/admin/users/${userId}/toggle`, {}, token);
}

export async function deleteUser(userId: number, token?: string): Promise<{ status: string }> {
  return apiDelete<{ status: string }>(`/api/admin/users/${userId}`, token);
}

// Package API functions
export async function fetchPackages<T>(token?: string): Promise<T> {
  return apiGet<T>("/api/admin/packages", token);
}

export async function createPackage<TRequest, TResponse>(payload: TRequest, token?: string): Promise<TResponse> {
  return apiPost<TRequest, TResponse>("/api/admin/packages", payload, token);
}

export async function updatePackage<TRequest, TResponse>(packageId: number, payload: TRequest, token?: string): Promise<TResponse> {
  return apiPatch<TRequest, TResponse>(`/api/admin/packages/${packageId}`, payload, token);
}

export async function deletePackage<TResponse>(packageId: number, token?: string): Promise<TResponse> {
  return apiDelete<TResponse>(`/api/admin/packages/${packageId}`, token);
}

export async function pollUntilTaskComplete(taskId: string, token?: string, maxAttempts: number = 600, intervalMs: number = 1000): Promise<TaskStatusResponse> {
  let lastKnownStatus: TaskStatusResponse["status"] | null = null;

  for (let i = 0; i < maxAttempts; i++) {
    try {
      const task = await apiGet<TaskStatusResponse>(`/api/tasks/${taskId}`, token);
      lastKnownStatus = task.status;
      if (task.status !== "running") {
        return task;
      }
    } catch (error) {
      if (
        error instanceof Error
        && error.message.includes("Task not found")
        && lastKnownStatus !== null
        && lastKnownStatus !== "running"
      ) {
        return {
          task_id: taskId,
          task_type: "",
          description: "",
          status: lastKnownStatus,
          progress: 1,
          metadata: {},
          created_at: 0,
          error: null,
        } as TaskStatusResponse;
      }
      throw error;
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error("Upload timed out");
}
