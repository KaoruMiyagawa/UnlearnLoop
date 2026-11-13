import { apiRequest } from './client.ts';
import type { CompleteReviewRequest, ReviewItem } from './types.ts';

export interface ListReviewsQuery {
  learner_id?: string;
  status?: 'pending' | 'completed';
}

export function listReviews(query: ListReviewsQuery = {}, signal?: AbortSignal): Promise<ReviewItem[]> {
  const params = new URLSearchParams();
  if (query.learner_id !== undefined) params.set('learner_id', query.learner_id);
  if (query.status !== undefined) params.set('status', query.status);
  const suffix = params.size ? `?${params.toString()}` : '';
  return apiRequest(`/api/v1/reviews${suffix}`, { method: 'GET', signal });
}

export function getReview(reviewId: string, learnerId = 'default_learner', signal?: AbortSignal): Promise<ReviewItem> {
  const params = new URLSearchParams({ learner_id: learnerId });
  return apiRequest(`/api/v1/reviews/${encodeURIComponent(reviewId)}?${params}`, { method: 'GET', signal });
}

export function startReview(reviewId: string, learnerId = 'default_learner', signal?: AbortSignal): Promise<ReviewItem> {
  const params = new URLSearchParams({ learner_id: learnerId });
  return apiRequest(`/api/v1/reviews/${encodeURIComponent(reviewId)}/start?${params}`, { method: 'POST', signal });
}

export function completeReview(
  reviewId: string,
  payload?: CompleteReviewRequest,
  signal?: AbortSignal,
): Promise<ReviewItem> {
  return apiRequest(`/api/v1/reviews/${encodeURIComponent(reviewId)}/complete`, {
    method: 'POST',
    ...(payload ? { body: JSON.stringify(payload) } : {}),
    signal,
  });
}
