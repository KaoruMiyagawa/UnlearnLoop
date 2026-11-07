import { apiRequest } from './client.ts';
import type {
  DiagnosticCase,
  DiagnosticStepRequest,
  DiagnosticStepResponse,
  EvidenceLink,
  Hypothesis,
} from './types.ts';

export function getDiagnosis(caseId: string, signal?: AbortSignal): Promise<DiagnosticCase> {
  return apiRequest(`/api/v1/diagnoses/${encodeURIComponent(caseId)}`, { method: 'GET', signal });
}

export function listHypotheses(caseId: string, signal?: AbortSignal): Promise<Hypothesis[]> {
  return apiRequest(`/api/v1/diagnoses/${encodeURIComponent(caseId)}/hypotheses`, { method: 'GET', signal });
}

export function listEvidence(caseId: string, signal?: AbortSignal): Promise<EvidenceLink[]> {
  return apiRequest(`/api/v1/diagnoses/${encodeURIComponent(caseId)}/evidence`, { method: 'GET', signal });
}

function postDiagnosticAction(
  caseId: string,
  action: 'step' | 'retry',
  payload: DiagnosticStepRequest = {},
  signal?: AbortSignal,
): Promise<DiagnosticStepResponse> {
  return apiRequest(`/api/v1/diagnoses/${encodeURIComponent(caseId)}/${action}`, {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}

export const runDiagnosticStep = (id: string, payload?: DiagnosticStepRequest, signal?: AbortSignal) =>
  postDiagnosticAction(id, 'step', payload, signal);
export const retryDiagnosticStep = (id: string, payload?: DiagnosticStepRequest, signal?: AbortSignal) =>
  postDiagnosticAction(id, 'retry', payload, signal);
