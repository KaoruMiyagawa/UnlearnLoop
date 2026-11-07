import { apiRequest } from './client.ts';
import type { DashboardSummary, KnowledgeState } from './types.ts';

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
