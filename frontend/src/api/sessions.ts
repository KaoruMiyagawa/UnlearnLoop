import { ApiClientError, apiRequest } from './client.ts';
import type {
  AttemptAnswer,
  AttemptDetail,
  AttemptResult,
  AttemptSummary,
  CreateSessionRequest,
  DispatchTransferRequest,
  SessionActionRequest,
  SessionDetail,
  SessionStatus,
  SessionSummary,
  LearningMaterial,
  SubmitAttemptRequest,
  TransferCheckDispatchResponse,
} from './types.ts';

export interface ListSessionsQuery {
  learner_id?: string;
  status?: SessionStatus;
}

export function createSession(payload: CreateSessionRequest, signal?: AbortSignal): Promise<SessionDetail> {
  return apiRequest('/api/v1/sessions', { method: 'POST', body: JSON.stringify(payload), signal });
}

export function listSessions(query: ListSessionsQuery = {}, signal?: AbortSignal): Promise<SessionSummary[]> {
  const params = new URLSearchParams();
  if (query.learner_id !== undefined) params.set('learner_id', query.learner_id);
  if (query.status !== undefined) params.set('status', query.status);
  const suffix = params.size ? `?${params.toString()}` : '';
  return apiRequest(`/api/v1/sessions${suffix}`, { method: 'GET', signal });
}

export function getSession(sessionId: string, signal?: AbortSignal): Promise<SessionDetail> {
  return apiRequest(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, { method: 'GET', signal });
}

export function getSessionMaterial(sessionId: string, signal?: AbortSignal): Promise<LearningMaterial | null> {
  return apiRequest(`/api/v1/sessions/${encodeURIComponent(sessionId)}/material`, { method: 'GET', signal });
}

function postSessionAction(
  sessionId: string,
  action: 'pause' | 'resume' | 'complete',
  payload?: SessionActionRequest,
  signal?: AbortSignal,
): Promise<SessionDetail> {
  return apiRequest(`/api/v1/sessions/${encodeURIComponent(sessionId)}/${action}`, {
    method: 'POST',
    ...(payload ? { body: JSON.stringify(payload) } : {}),
    signal,
  });
}

export const pauseSession = (id: string, payload?: SessionActionRequest, signal?: AbortSignal) =>
  postSessionAction(id, 'pause', payload, signal);
export const resumeSession = (id: string, payload?: SessionActionRequest, signal?: AbortSignal) =>
  postSessionAction(id, 'resume', payload, signal);
export const completeSession = (id: string, payload?: SessionActionRequest, signal?: AbortSignal) =>
  postSessionAction(id, 'complete', payload, signal);

export function createAttemptSubmission(
  input: AttemptAnswer & { question_id: string; idempotency_key?: string | null },
): Readonly<SubmitAttemptRequest> {
  const idempotency_key = input.idempotency_key ?? crypto.randomUUID();
  if (input.structured_answer) {
    return Object.freeze({
      question_id: input.question_id,
      group_version_id: input.group_version_id,
      structured_answer: Object.freeze({ ...input.structured_answer }),
      idempotency_key,
    });
  }
  return Object.freeze({ question_id: input.question_id, submitted_answer: input.submitted_answer, idempotency_key });
}

export function attemptContent(payload: AttemptAnswer & { question_id: string }): string {
  return JSON.stringify(payload.structured_answer
    ? [payload.question_id, payload.group_version_id, Object.entries(payload.structured_answer).sort(([a], [b]) => a.localeCompare(b))]
    : [payload.question_id, payload.submitted_answer]);
}
// Retained only for this page lifetime. The backend remains authoritative and
// persists the same-key/same-content check across reloads and other clients.
const submittedAttemptBodies = new Map<string, string>();

/**
 * Submit the prepared intent. Reuse its frozen payload for retries; create a
 * new payload (and key) for a genuinely new answer.
 */
export function submitAttempt(
  sessionId: string,
  payload: SubmitAttemptRequest,
  signal?: AbortSignal,
): Promise<AttemptResult> {
  const body = JSON.stringify(payload);
  if (payload.idempotency_key) {
    const requestIdentity = JSON.stringify([sessionId, payload.idempotency_key]);
    const requestContent = attemptContent(payload);
    const previousContent = submittedAttemptBodies.get(requestIdentity);
    if (previousContent !== undefined && previousContent !== requestContent) {
      return Promise.reject(new ApiClientError(409, {
        code: 'IDEMPOTENCY_CONFLICT',
        message: '该幂等键已用于不同的作答内容。新作答请创建新的提交请求。',
      }));
    }
    submittedAttemptBodies.set(requestIdentity, requestContent);
  }
  return apiRequest(`/api/v1/sessions/${encodeURIComponent(sessionId)}/attempts`, {
    method: 'POST',
    body,
    signal,
  });
}

export function listSessionAttempts(sessionId: string, signal?: AbortSignal): Promise<AttemptSummary[]> {
  return apiRequest(`/api/v1/sessions/${encodeURIComponent(sessionId)}/attempts`, { method: 'GET', signal });
}

export function getAttempt(attemptId: string, signal?: AbortSignal): Promise<AttemptDetail> {
  return apiRequest(`/api/v1/attempts/${encodeURIComponent(attemptId)}`, { method: 'GET', signal });
}

export function dispatchTransferCheck(
  sessionId: string,
  payload: DispatchTransferRequest = {},
  signal?: AbortSignal,
): Promise<TransferCheckDispatchResponse> {
  return apiRequest(`/api/v1/sessions/${encodeURIComponent(sessionId)}/transfer-check`, {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}
