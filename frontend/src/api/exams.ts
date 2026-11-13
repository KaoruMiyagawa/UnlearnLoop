import { apiRequest } from './client.ts';
import type { ExamCatalogEntry, ExamPreparationProfile, ExamPreparationProfileUpdate } from './types.ts';

const learnerQuery = (learnerId: string) => `?learner_id=${encodeURIComponent(learnerId)}`;
export const getExamCatalog = (signal?: AbortSignal) => apiRequest<ExamCatalogEntry[]>('/api/v1/exams/catalog', { method: 'GET', signal });
export const getExamProfile = (learnerId = 'default_learner', signal?: AbortSignal) => apiRequest<ExamPreparationProfile>(`/api/v1/profile/exam-preparation${learnerQuery(learnerId)}`, { method: 'GET', signal });
export const saveExamProfile = (payload: ExamPreparationProfileUpdate, learnerId = 'default_learner', signal?: AbortSignal) => apiRequest<ExamPreparationProfile>(`/api/v1/profile/exam-preparation${learnerQuery(learnerId)}`, { method: 'PUT', body: JSON.stringify(payload), signal });
