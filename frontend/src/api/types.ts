/**
 * Frontend representations derived from the FastAPI OpenAPI schema.
 * Learner-facing question types intentionally omit standard answers and rubrics.
 */
export interface ApiErrorResponse {
  code: string;
  message: string;
  request_id: string;
  details?: Record<string, unknown>;
}

export type RuntimeEnvironment = 'development' | 'testing' | 'production';
export type QuestionRole =
  | 'initial'
  | 'diagnostic_followup'
  | 'targeted_practice'
  | 'transfer_check'
  | 'review';
export type QuestionType =
  | 'short_text'
  | 'code_trace'
  | 'code_writing'
  | 'multiple_choice';
export type SessionStatus =
  | 'active'
  | 'diagnosing'
  | 'intervening'
  | 'transfer_checking'
  | 'reviewing'
  | 'completed'
  | 'paused';
export type DiagnosticCaseStatus =
  | 'collecting_attempt'
  | 'initial_evaluated'
  | 'hypotheses_generated'
  | 'needs_evidence'
  | 'question_selected'
  | 'hypotheses_updated'
  | 'intervention_selected'
  | 'transfer_checking'
  | 'resolved'
  | 'insufficient_evidence'
  | 'retry_waiting'
  | 'paused';
export type HypothesisStatus =
  | 'candidate'
  | 'insufficient_evidence'
  | 'supported'
  | 'lowered'
  | 'ruled_out'
  | 'confirmed';
export type EvidenceSourceType =
  | 'initial_attempt'
  | 'followup_response'
  | 'practice_attempt'
  | 'transfer_attempt'
  | 'rule_check'
  | 'model_evaluation';
export type EvidenceRelation = 'supports' | 'contradicts' | 'neutral';
export type UncertaintyLevel = 'low' | 'medium' | 'high' | 'insufficient_evidence';
export type KnowledgeMasteryStatus =
  | 'insufficient_evidence'
  | 'needs_diagnosis'
  | 'needs_practice'
  | 'stable';

export interface SubsystemReadiness {
  persistence: 'configured' | 'unconfigured';
  model_provider: string;
  remote_model_enabled: boolean;
}

export interface HealthResponse {
  status: 'ok';
  service: string;
  version: string;
  environment: RuntimeEnvironment;
  stage?: string;
  timestamp: string;
  request_id: string;
  subsystems: SubsystemReadiness;
}

export interface TopicSummary {
  id: string;
  slug: string;
  domain_code: string;
  title: string;
  summary: string;
  difficulty_level: number;
  prerequisite_ids?: string[];
}

export interface TopicPrerequisiteSummary {
  id: string;
  slug: string;
  title: string;
}

export interface LearningMaterial {
  id: string;
  topic_id: string;
  title: string;
  summary: string;
  content_body: string;
  content_format: string;
  version: number;
}

export interface TopicDetail extends TopicSummary {
  prerequisites?: TopicPrerequisiteSummary[];
  materials?: LearningMaterial[];
  questions_count: number;
}

export interface SanitizedQuestion {
  id: string;
  topic_id: string;
  material_id?: string | null;
  parent_question_id?: string | null;
  question_role: QuestionRole;
  question_type: QuestionType;
  prompt_text: string;
  context_snippet?: string | null;
  difficulty: number;
  version: number;
}

export interface CreateSessionRequest {
  topic_id: string;
  learner_id?: string;
  initial_question_id?: string | null;
}

export interface SessionActionRequest {
  reason?: string | null;
}

export interface SessionSummary {
  id: string;
  topic_id: string;
  topic_title: string;
  learner_id: string;
  status: SessionStatus;
  knowledge_state_status?: KnowledgeMasteryStatus | null;
  topic_mastered?: boolean;
  current_question_id?: string | null;
  attempts_count?: number;
  started_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface SessionDetail extends SessionSummary {
  current_question?: SanitizedQuestion | null;
  active_diagnostic_case_id?: string | null;
  latest_attempt_result?: AttemptResult | null;
  can_dispatch_transfer?: boolean;
}

export interface SubmitAttemptRequest {
  question_id: string;
  submitted_answer: string;
  idempotency_key?: string | null;
}

export interface AttemptSummary {
  id: string;
  session_id: string;
  question_id: string;
  question_role: string;
  submitted_answer: string;
  is_correct?: boolean | null;
  evaluation_status: string;
  evaluation_summary?: string | null;
  submitted_at: string;
}

export interface AttemptDetail extends AttemptSummary {
  question_version: number;
  idempotency_key?: string | null;
  diagnostic_case_id?: string | null;
  evaluation_source?: string | null;
}

export interface AttemptResult {
  attempt_id: string;
  session_id: string;
  question_id: string;
  question_role: string;
  is_correct?: boolean | null;
  evaluation_summary?: string | null;
  feedback_text?: string | null;
  next_action: string;
  next_question?: SanitizedQuestion | null;
  diagnostic_case_id?: string | null;
  knowledge_state_status?: string | null;
  evaluation_source?: string;
  mastery_note?: string | null;
}

export interface Hypothesis {
  id: string;
  diagnostic_case_id: string;
  error_code: string;
  name: string;
  description?: string | null;
  confidence: number;
  status: HypothesisStatus;
  missing_evidence_desc?: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvidenceLink {
  id: string;
  hypothesis_id: string;
  attempt_id?: string | null;
  source_type: EvidenceSourceType;
  source_ref: string;
  relation: EvidenceRelation;
  summary: string;
  reliability_note?: string | null;
  created_at: string;
}

export interface ModelExecutionMetadata {
  model_provider_name: string;
  is_mock_provider: boolean;
  /** OpenAPI currently exposes this as string; interpret known values conservatively. */
  execution_mode: string;
}

export type ModelExecutionKind = 'mock' | 'live' | 'unknown';

export function getModelExecutionKind(
  metadata: ModelExecutionMetadata,
): ModelExecutionKind {
  if (metadata.is_mock_provider && metadata.execution_mode === 'mock') return 'mock';
  if (
    !metadata.is_mock_provider &&
    metadata.execution_mode === 'live' &&
    metadata.model_provider_name !== 'fake'
  ) return 'live';
  return 'unknown';
}

export interface DiagnosticCase extends ModelExecutionMetadata {
  id: string;
  session_id: string;
  trigger_attempt_id: string;
  status: DiagnosticCaseStatus;
  uncertainty_level: UncertaintyLevel;
  uncertainty_note?: string | null;
  followup_turn_count: number;
  tokens_used: number;
  hypotheses?: Hypothesis[];
  evidence_count?: number;
  created_at: string;
  updated_at: string;
}

export interface DiagnosticStepRequest {
  idempotency_key?: string | null;
}

export interface DiagnosticStepResponse extends ModelExecutionMetadata {
  session_id: string;
  diagnostic_case_id: string;
  case_status: DiagnosticCaseStatus;
  executed_tool: string;
  selected_intervention?: string | null;
  selected_question_id?: string | null;
  next_question?: SanitizedQuestion | null;
  explanation_text?: string | null;
  uncertainty_level: UncertaintyLevel;
  uncertainty_note?: string | null;
  confidence_is_heuristic?: boolean;
  followup_turns_used: number;
  max_followup_turns: number;
  tokens_used_in_case: number;
  session_token_budget: number;
  degraded_mode?: boolean;
  degradation_reason?: string | null;
  knowledge_state_status?: string | null;
  hypotheses?: Array<Record<string, unknown>>;
}

export interface DispatchTransferRequest {
  force_fresh?: boolean;
}

export interface TransferCheckDispatchResponse {
  question?: SanitizedQuestion | null;
  session_status: SessionStatus;
  degraded?: boolean;
  message: string;
}

export interface ReviewItem {
  id: string;
  topic_id: string;
  topic_title: string;
  session_id?: string | null;
  learner_id: string;
  trigger_reason: string;
  scheduled_for: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  review_stage?: number;
  review_session_id?: string | null;
  question_id?: string | null;
  current_question?: SanitizedQuestion | null;
  review_question?: SanitizedQuestion | null;
  attempt_id?: string | null;
  is_correct?: boolean | null;
  submitted_at?: string | null;
  evaluation_summary?: string | null;
  review_outcome?: string | null;
  retention_verified?: boolean;
  retention_eligible?: boolean;
  decision_event_id?: string | null;
  message?: string | null;
  is_due?: boolean;
  knowledge_state_id?: string | null;
}

export interface CompleteReviewRequest {
  review_notes?: string | null;
}

export interface KnowledgeState {
  id: string;
  learner_id: string;
  topic_id: string;
  topic_title: string;
  topic_slug: string;
  status: KnowledgeMasteryStatus;
  confidence_is_heuristic?: boolean;
  unresolved_error_codes?: string[];
  transition_reason?: string | null;
  last_transfer_attempt_id?: string | null;
  updated_at: string;
  retention_status?: 'not_verified' | 'review_due' | 'delayed_check_passed' | 'review_failed';
  retention_evidence_count?: number;
  last_reviewed_at?: string | null;
  last_retention_verified_at?: string | null;
  unresolved_error_reasons?: Array<{ title: string; summary: string; status: string }>;
}

export interface LearningHistoryEvent {
  id: string;
  kind: string;
  occurred_at: string;
  topic_id: string;
  topic_title: string;
  title: string;
  summary: string;
  evidence_summary: string;
  session_id?: string | null;
  attempt_id?: string | null;
  review_id?: string | null;
}

export interface DashboardSummary {
  learner_id: string;
  total_sessions: number;
  active_sessions: number;
  completed_sessions: number;
  total_attempts: number;
  pending_reviews_count: number;
  mastered_topics_count: number;
  needs_practice_topics_count: number;
  recent_sessions?: SessionSummary[];
  pending_reviews?: ReviewItem[];
}
