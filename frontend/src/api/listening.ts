import { apiRequest } from './client';

export interface ListeningQuestion { id: string; prompt: string; options: string[]; number: number; correct_answer?: string; explanation?: string; start_seconds?: number; end_seconds?: number; }
export interface ListeningLesson { id: string; title: string; scenario: string; duration_seconds: number; audio_url: string; content_version: string; evaluation_rule_version: string; evaluation_source: 'rule_check'; audio_source: string; rights: string; questions: ListeningQuestion[]; }
export interface ListeningResult { question: ListeningQuestion; submitted_answer: string; is_correct: boolean; }
export interface ListeningSession { session_id: string; status: string; lesson: ListeningLesson; answers: Record<string, string>; score?: number; results?: ListeningResult[]; assessment_note?: string; }
export interface ListeningHistory { session_id: string; started_at: string; completed_at: string | null; status: string; score: number | null; }
export const startListeningSession = (learner_id = 'default_learner') => apiRequest<ListeningSession>('/api/v1/listening/sessions', { method: 'POST', body: JSON.stringify({ learner_id }) });
export const getListeningSession = (id: string, learner_id = 'default_learner') => apiRequest<ListeningSession>(`/api/v1/listening/sessions/${encodeURIComponent(id)}?learner_id=${encodeURIComponent(learner_id)}`);
export const submitListeningSession = (id: string, answers: Record<string, string>, idempotency_key: string, learner_id = 'default_learner') => apiRequest<ListeningSession>(`/api/v1/listening/sessions/${encodeURIComponent(id)}/submit?learner_id=${encodeURIComponent(learner_id)}`, { method: 'POST', body: JSON.stringify({ answers, idempotency_key }) });
export const getListeningHistory = () => apiRequest<ListeningHistory[]>('/api/v1/listening/history?learner_id=default_learner');
