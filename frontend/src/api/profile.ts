import { apiRequest } from './client.ts';
import type { DashboardSummary, EvidenceRevalidationRequest, EvidenceRevalidationResponse, KnowledgeState, LearningHistoryEvent } from './types.ts';

function learnerQuery(learnerId?: string): string {
  if (learnerId === undefined) return '';
  const params = new URLSearchParams({ learner_id: learnerId });
  return `?${params.toString()}`;
}

export function listKnowledgeStates(learnerId?: string, signal?: AbortSignal): Promise<KnowledgeState[]> {
  return apiRequest(`/api/v1/profile/knowledge-states${learnerQuery(learnerId)}`, { method: 'GET', signal });
}

export function getProfileSummary(learnerId?: string, signal?: AbortSignal): Promise<DashboardSummary> {
  return apiRequest(`/api/v1/profile/summary${learnerQuery(learnerId)}`, { method: 'GET', signal });
}

export function listLearningHistory(
  learnerId?: string,
  limit = 100,
  signal?: AbortSignal,
): Promise<LearningHistoryEvent[]> {
  const params = new URLSearchParams();
  if (learnerId !== undefined) params.set('learner_id', learnerId);
  params.set('limit', String(limit));
  return apiRequest(`/api/v1/profile/history?${params.toString()}`, { method: 'GET', signal });
}

export function startEvidenceRevalidation(
  request: EvidenceRevalidationRequest,
  signal?: AbortSignal,
): Promise<EvidenceRevalidationResponse> {
  return apiRequest('/api/v1/profile/evidence-revalidation', {
    method: 'POST',
    body: JSON.stringify(request),
    signal,
  });
}
