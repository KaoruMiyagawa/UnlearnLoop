import { apiRequest } from './client.ts';

export interface WritingTask {
  version: string;
  title: string;
  prompt: string;
  instruction: string;
  suggested_words: number;
  max_characters: number;
  checklist: string[];
}

export interface WritingDraft {
  body: string;
  version: number;
  updated_at: string;
}

export interface WritingFeedback {
  method: 'deterministic_text_metrics';
  rule_version: string;
  confidence: 'observable_text_only';
  semantic_quality: 'not_assessed';
  word_count: number;
  below_suggested_words: boolean;
  paragraph_blocks: number;
  word_count_change: number | null;
}

export interface WritingRevisionSummary {
  id: string;
  number: number;
  source_revision_id: string | null;
  submitted_at: string;
  feedback: WritingFeedback;
}

export interface WritingRevision extends WritingRevisionSummary {
  body: string;
}

export interface WritingSession {
  session_id: string;
  task: WritingTask;
  draft: WritingDraft;
  revisions: WritingRevisionSummary[];
}

type DraftInput = Pick<WritingDraft, 'body' | 'version'>;
export type WritingSubmission = DraftInput & { idempotency_key: string };
const BASE = '/api/v1/writing/sessions';
const LEARNER = 'default_learner';
const query = new URLSearchParams({ learner_id: LEARNER });

export function openWriting(signal?: AbortSignal) {
  return apiRequest<WritingSession>(BASE, {
    method: 'POST', body: JSON.stringify({ learner_id: LEARNER }), signal,
  });
}

export function saveWritingDraft(session: string, input: DraftInput) {
  return apiRequest<WritingDraft>(`${BASE}/${encodeURIComponent(session)}/draft?${query}`, {
    method: 'PUT', body: JSON.stringify(input),
  });
}

export function submitWriting(session: string, input: WritingSubmission) {
  return apiRequest<WritingRevision>(`${BASE}/${encodeURIComponent(session)}/revisions?${query}`, {
    method: 'POST', body: JSON.stringify(input),
  });
}

export function getWritingRevision(session: string, revision: string) {
  return apiRequest<WritingRevision>(`${BASE}/${encodeURIComponent(session)}/revisions/${encodeURIComponent(revision)}?${query}`);
}
