import { apiRequest } from './client.ts';
import type {
  LearningMaterial,
  SanitizedQuestion,
  TopicDetail,
  TopicSummary,
} from './types.ts';

export interface ListTopicsQuery {
  domain_code?: string;
}

function queryString(query: ListTopicsQuery): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined) params.set(key, value);
  });
  const serialized = params.toString();
  return serialized ? `?${serialized}` : '';
}

export function listTopics(query: ListTopicsQuery = {}, signal?: AbortSignal): Promise<TopicSummary[]> {
  return apiRequest(`/api/v1/topics${queryString(query)}`, { method: 'GET', signal });
}

export function getTopic(topicIdOrSlug: string, signal?: AbortSignal): Promise<TopicDetail> {
  return apiRequest(`/api/v1/topics/${encodeURIComponent(topicIdOrSlug)}`, { method: 'GET', signal });
}

export function getTopicMaterials(topicIdOrSlug: string, signal?: AbortSignal): Promise<LearningMaterial[]> {
  return apiRequest(`/api/v1/topics/${encodeURIComponent(topicIdOrSlug)}/materials`, { method: 'GET', signal });
}

export function getSanitizedQuestion(questionId: string, signal?: AbortSignal): Promise<SanitizedQuestion> {
  return apiRequest(`/api/v1/questions/${encodeURIComponent(questionId)}`, { method: 'GET', signal });
}
