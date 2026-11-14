import { apiRequest } from './client';

export interface SpeakingPrompt {
  id: string;
  text: string;
  version: string;
  part: number;
  suggested_seconds: number;
}

export interface SpeakingMetadata {
  learner_id: string;
  recording_id: string;
  prompt_id: string;
  prompt_version: string;
  duration_seconds: number;
  recorded_at: string;
  self_check: string[];
}

export interface SpeakingPractice extends Omit<SpeakingMetadata, 'learner_id'> {
  session_id: string;
  prompt_text: string;
  completed_at: string;
  evaluation_status: 'not_assessed';
  evidence_type: 'practice_only';
  note: string;
}

const base = '/api/v1/speaking';
export const getSpeakingPrompts = () => apiRequest<SpeakingPrompt[]>(`${base}/prompts`);
export const getSpeakingPractices = (learner: string) =>
  apiRequest<SpeakingPractice[]>(`${base}/practices?learner_id=${encodeURIComponent(learner)}`);
export const completeSpeaking = (metadata: SpeakingMetadata) =>
  apiRequest<SpeakingPractice>(`${base}/practices`, { method: 'POST', body: JSON.stringify(metadata) });
export const deleteSpeakingPractice = (id: string, learner: string) =>
  apiRequest<{ deleted: boolean }>(`${base}/practices/${encodeURIComponent(id)}?learner_id=${encodeURIComponent(learner)}`, { method: 'DELETE' });
