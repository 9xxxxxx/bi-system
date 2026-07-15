export interface BackendReadiness {
  status: string;
  database: string;
}

interface ApiProblemDetail {
  code?: string;
  message?: string;
  action?: string;
}

export class ApiError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly action?: string;

  constructor(
    message: string,
    options: { status?: number; code?: string; action?: string } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.action = options.action;
  }
}

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const REQUEST_TIMEOUT_MS = 30_000;

async function parseApiError(response: Response): Promise<ApiError> {
  let detail: ApiProblemDetail | undefined;
  try {
    const payload = (await response.json()) as {
      detail?: ApiProblemDetail | string;
    };
    if (typeof payload.detail === "string") {
      detail = { message: payload.detail };
    } else {
      detail = payload.detail;
    }
  } catch {
    detail = undefined;
  }

  return new ApiError(detail?.message ?? "API request failed", {
    status: response.status,
    code: detail?.code,
    action: detail?.action,
  });
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS,
  );
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw await parseApiError(response);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function getBackendReadiness(): Promise<BackendReadiness> {
  return requestJson<BackendReadiness>("/health/ready");
}
