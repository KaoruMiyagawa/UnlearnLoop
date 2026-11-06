/**
 * Minimal REST API client wrapper for UnlearnLoop.
 * Adheres to ARCHITECTURE.md Section 3 & 5:
 * - Versioned /api/v1 endpoints
 * - Structured error handling with code, message, and request_id
 * - Explicit timeout control
 */

export interface ApiErrorPayload {
  code: string;
  message: string;
  request_id?: string;
  details?: unknown;
}

export class ApiClientError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly requestId?: string;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = payload.code;
    this.requestId = payload.request_id;
  }
}

const DEFAULT_TIMEOUT_MS = 8000;

export function getApiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!configured) {
    return 'http://127.0.0.1:18000';
  }
  return configured.replace(/\/+$/, '');
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const url = `${getApiBaseUrl()}${normalizedPath}`;

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
      signal: controller.signal,
    });

    const headerRequestId = response.headers.get('X-Request-ID') ?? undefined;

    if (!response.ok) {
      let errorPayload: ApiErrorPayload = {
        code: `HTTP_${response.status}`,
        message: `请求失败（HTTP ${response.status}）`,
        request_id: headerRequestId,
      };
      try {
        const parsed = (await response.json()) as Partial<ApiErrorPayload>;
        if (parsed && typeof parsed.message === 'string') {
          errorPayload = {
            code: parsed.code ?? errorPayload.code,
            message: parsed.message,
            request_id: parsed.request_id ?? headerRequestId,
            details: parsed.details,
          };
        }
      } catch {
        // Ignore JSON parse failure on non-JSON error responses
      }
      throw new ApiClientError(response.status, errorPayload);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiClientError(0, {
        code: 'REQUEST_TIMEOUT',
        message: '连接后端服务超时，请检查后端服务是否已启动。',
      });
    }
    throw new ApiClientError(0, {
      code: 'NETWORK_ERROR',
      message: '无法连接后端服务，请确认后端已在本地启动并监听对应端口。',
    });
  } finally {
    window.clearTimeout(timer);
  }
}
