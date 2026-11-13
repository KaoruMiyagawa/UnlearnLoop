/** Shared HTTP transport for the versioned FastAPI contract. */
export interface ApiErrorPayload {
  code: string;
  message: string;
  request_id?: string;
  details?: unknown;
}

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly details?: unknown;
  readonly retryable: boolean;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = payload.code;
    this.requestId = payload.request_id;
    this.details = payload.details;
    this.retryable = isRetryableStatus(status, payload.code);
  }
}

export type AsyncResourceState<T> =
  | { status: 'idle' }
  | { status: 'loading'; data?: T }
  | { status: 'success'; data: T }
  | { status: 'error'; error: ApiClientError; data?: T };

export type ResourceLoader<T> = (signal: AbortSignal) => Promise<T>;
export type ResourceListener<T> = (state: AsyncResourceState<T>) => void;

const DEFAULT_TIMEOUT_MS = 8_000;

export function getApiBaseUrl(): string {
  const configured = import.meta.env?.VITE_API_BASE_URL?.trim();
  return (configured || 'http://127.0.0.1:18000').replace(/\/+$/, '');
}

function isRetryableStatus(status: number, code: string): boolean {
  if (code === 'REQUEST_TIMEOUT' || code === 'NETWORK_ERROR') return true;
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

function normalizeErrorPayload(
  parsed: unknown,
  status: number,
  requestId?: string,
): ApiErrorPayload {
  const fallback: ApiErrorPayload = {
    code: `HTTP_${status}`,
    message: `请求失败（HTTP ${status}）`,
    request_id: requestId,
  };
  if (!parsed || typeof parsed !== 'object') return fallback;

  const body = parsed as Partial<ApiErrorPayload>;
  if (typeof body.message !== 'string') return fallback;
  return {
    code: typeof body.code === 'string' ? body.code : fallback.code,
    message: body.message,
    request_id:
      typeof body.request_id === 'string' ? body.request_id : requestId,
    details: body.details,
  };
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const callerSignal = options.signal;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const abortFromCaller = () => controller.abort();
  if (callerSignal?.aborted) controller.abort();
  callerSignal?.addEventListener('abort', abortFromCaller, { once: true });

  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const url = `${getApiBaseUrl()}${normalizedPath}`;
  const headers = new Headers(options.headers);
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      const requestId = response.headers.get('X-Request-ID') ?? undefined;
      let parsed: unknown;
      try {
        parsed = await response.json();
      } catch {
        parsed = undefined;
      }
      throw new ApiClientError(
        response.status,
        normalizeErrorPayload(parsed, response.status, requestId),
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiClientError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiClientError(0, {
        code: timedOut ? 'REQUEST_TIMEOUT' : 'REQUEST_ABORTED',
        message: timedOut
          ? '连接后端服务超时，请检查后端服务是否已启动。'
          : '请求已取消。',
      });
    }
    throw new ApiClientError(0, {
      code: 'NETWORK_ERROR',
      message: '无法连接后端服务，请确认后端已启动并监听对应端口。',
    });
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', abortFromCaller);
  }
}

/**
 * Small observable request state for screens that need loading/error/retry.
 * A loader is kept so retry repeats the same operation and captured payload.
 */
export class ApiResource<T> {
  private currentState: AsyncResourceState<T> = { status: 'idle' };
  private readonly listeners = new Set<ResourceListener<T>>();
  private activeController?: AbortController;
  private readonly loader: ResourceLoader<T>;

  constructor(loader: ResourceLoader<T>) {
    this.loader = loader;
  }

  get state(): AsyncResourceState<T> {
    return this.currentState;
  }

  subscribe(listener: ResourceListener<T>): () => void {
    this.listeners.add(listener);
    listener(this.currentState);
    return () => this.listeners.delete(listener);
  }

  async load(): Promise<T> {
    this.activeController?.abort();
    const controller = new AbortController();
    this.activeController = controller;
    const previousData = this.currentState.status === 'idle'
      ? undefined
      : this.currentState.data;
    this.setState({ status: 'loading', ...(previousData !== undefined ? { data: previousData } : {}) });

    try {
      const data = await this.loader(controller.signal);
      if (this.activeController === controller) {
        this.setState({ status: 'success', data });
      }
      return data;
    } catch (cause) {
      const error = cause instanceof ApiClientError
        ? cause
        : new ApiClientError(0, {
            code: 'REQUEST_ERROR',
            message: cause instanceof Error ? cause.message : '请求失败。',
          });
      if (this.activeController === controller) {
        this.setState({
          status: 'error',
          error,
          ...(previousData !== undefined ? { data: previousData } : {}),
        });
      }
      throw error;
    }
  }

  retry(): Promise<T> {
    return this.load();
  }

  reset(): void {
    this.activeController?.abort();
    this.activeController = undefined;
    this.setState({ status: 'idle' });
  }

  private setState(state: AsyncResourceState<T>): void {
    this.currentState = state;
    this.listeners.forEach((listener) => listener(state));
  }
}
