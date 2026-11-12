import { getDiagnosis, listEvidence, listHypotheses } from '../api/diagnoses.ts';
import { getAttempt } from '../api/sessions.ts';
import type {
  AttemptDetail,
  AttemptSummary,
  DiagnosticCase,
  DiagnosticStepRequest,
  EvidenceLink,
  Hypothesis,
  ModelExecutionKind,
  ModelExecutionMetadata,
  SessionDetail,
} from '../api/types.ts';
import { getModelExecutionKind } from '../api/types.ts';

export interface DiagnosticWorkspaceData {
  diagnosis: DiagnosticCase;
  hypotheses: Hypothesis[];
  evidence: EvidenceLink[];
  triggerAttempt: AttemptDetail;
}

export type DiagnosticStepAction = 'step' | 'retry';

export interface PendingDiagnosticIntent {
  caseId: string;
  action: DiagnosticStepAction;
  payload: Readonly<DiagnosticStepRequest>;
}

export function diagnosticExecutionDescription(
  diagnosis: Partial<ModelExecutionMetadata> | null,
  step: Partial<ModelExecutionMetadata> | null,
): { kind: ModelExecutionKind; provider: string } {
  if (step && diagnosis && (
    step.model_provider_name !== diagnosis.model_provider_name
    || step.is_mock_provider !== diagnosis.is_mock_provider
    || step.execution_mode !== diagnosis.execution_mode
  )) return { kind: 'unknown', provider: '来源元数据不一致' };

  const metadata = (step ?? diagnosis) as Partial<ModelExecutionMetadata> | null;
  if (
    !metadata
    || typeof metadata.model_provider_name !== 'string'
    || typeof metadata.is_mock_provider !== 'boolean'
    || typeof metadata.execution_mode !== 'string'
  ) return { kind: 'unknown', provider: '服务端未提供完整模型来源' };
  return {
    kind: getModelExecutionKind(metadata as ModelExecutionMetadata),
    provider: metadata.model_provider_name || 'unknown',
  };
}

const RUNNABLE_CASE_STATUSES = new Set([
  'collecting_attempt',
  'initial_evaluated',
  'hypotheses_generated',
  'needs_evidence',
  'question_selected',
  'hypotheses_updated',
  'intervention_selected',
]);

const TERMINAL_CASE_STATUSES = new Set(['resolved', 'insufficient_evidence', 'paused']);

export async function loadDiagnosticWorkspace(
  caseId: string,
  signal: AbortSignal,
): Promise<DiagnosticWorkspaceData> {
  const diagnosis = await getDiagnosis(caseId, signal);
  const [hypotheses, evidence, triggerAttempt] = await Promise.all([
    listHypotheses(caseId, signal),
    listEvidence(caseId, signal),
    getAttempt(diagnosis.trigger_attempt_id, signal),
  ]);
  return { diagnosis, hypotheses, evidence, triggerAttempt };
}

export function groupEvidenceByHypothesis(evidence: EvidenceLink[]): Map<string, EvidenceLink[]> {
  const grouped = new Map<string, EvidenceLink[]>();
  for (const item of evidence) {
    const bucket = grouped.get(item.hypothesis_id) ?? [];
    bucket.push(item);
    grouped.set(item.hypothesis_id, bucket);
  }
  return grouped;
}

export function canRunDiagnosticStep(
  session: SessionDetail | null,
  diagnosis: DiagnosticCase | null,
  attempts: AttemptSummary[] = [],
): boolean {
  if (session?.latest_attempt_result?.next_action === 'matching_headings_transfer_pending') return false;
  const currentQuestionId = session?.current_question_id ?? session?.current_question?.id;
  if (currentQuestionId && !attempts.some((attempt) => attempt.question_id === currentQuestionId)) {
    return false;
  }
  return Boolean(
    session
    && diagnosis
    && session.status !== 'paused'
    && session.status !== 'completed'
    && RUNNABLE_CASE_STATUSES.has(diagnosis.status)
    && !TERMINAL_CASE_STATUSES.has(diagnosis.status),
  );
}

export function canRetryDiagnosticStep(
  session: SessionDetail | null,
  diagnosis: DiagnosticCase | null,
): boolean {
  return Boolean(
    session
    && diagnosis?.status === 'retry_waiting'
    && session.status !== 'paused'
    && session.status !== 'completed',
  );
}

export function diagnosticIntentStorageKey(caseId: string): string {
  return `unlearnloop.real.diagnostic-step.v1.${caseId}`;
}

/** Persist a side-effecting decision intent so an explicit replay uses the same backend key. */
export function getOrCreateDiagnosticIntent(
  storage: Pick<Storage, 'getItem' | 'setItem'>,
  caseId: string,
  action: DiagnosticStepAction,
  createKey: () => string = () => globalThis.crypto.randomUUID(),
): PendingDiagnosticIntent {
  const storageKey = diagnosticIntentStorageKey(caseId);
  const stored = storage.getItem(storageKey);
  if (stored) {
    try {
      const pending = JSON.parse(stored) as PendingDiagnosticIntent;
      if (pending.caseId === caseId && pending.action === action && pending.payload?.idempotency_key) {
        return pending;
      }
      throw new Error('已有诊断步骤等待明确恢复；请先使用原操作重放。');
    } catch (error) {
      if (error instanceof Error && error.message.includes('等待明确恢复')) throw error;
      throw new Error('无法读取待恢复的诊断步骤；请先刷新服务端诊断状态。');
    }
  }

  const intent: PendingDiagnosticIntent = {
    caseId,
    action,
    payload: Object.freeze({ idempotency_key: createKey() }),
  };
  storage.setItem(storageKey, JSON.stringify(intent));
  return intent;
}

export function readPendingDiagnosticIntent(
  storage: Pick<Storage, 'getItem'>,
  caseId: string,
): PendingDiagnosticIntent | null {
  const stored = storage.getItem(diagnosticIntentStorageKey(caseId));
  if (!stored) return null;
  try {
    const value = JSON.parse(stored) as PendingDiagnosticIntent;
    return value.caseId === caseId && value.payload?.idempotency_key ? value : null;
  } catch {
    return null;
  }
}

export function clearPendingDiagnosticIntent(
  storage: Pick<Storage, 'removeItem'>,
  caseId: string,
): void {
  storage.removeItem(diagnosticIntentStorageKey(caseId));
}

export function diagnosticStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    collecting_attempt: '正在收集作答',
    initial_evaluated: '初始作答已评估',
    hypotheses_generated: '候选假设已生成',
    needs_evidence: '证据仍不足',
    question_selected: '已选择区分性追问',
    hypotheses_updated: '假设已根据新证据更新',
    intervention_selected: '已选择针对性干预',
    transfer_checking: '正在进行迁移验证',
    resolved: '诊断已完成',
    insufficient_evidence: '证据不足，暂不下结论',
    retry_waiting: '模型执行失败，等待明确重试',
    paused: '诊断已暂停',
  };
  return labels[value] ?? `未知诊断状态（${value}）`;
}

export function hypothesisStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    candidate: '待验证',
    insufficient_evidence: '证据不足',
    supported: '获得支持',
    lowered: '支持度降低',
    ruled_out: '已排除',
    confirmed: '当前证据确认',
  };
  return labels[value] ?? `未知假设状态（${value}）`;
}

export function evidenceRelationLabel(value: string): string {
  const labels: Record<string, string> = {
    supports: '支持',
    contradicts: '反对',
    neutral: '中性',
  };
  return labels[value] ?? `未知关系（${value}）`;
}

export function evidenceSourceLabel(value: string): string {
  const labels: Record<string, string> = {
    initial_attempt: '初始作答',
    followup_response: '追问回答',
    practice_attempt: '针对性练习',
    transfer_attempt: '迁移验证',
    rule_check: '规则检查',
    model_evaluation: '模型评估',
  };
  return labels[value] ?? `未知来源（${value}）`;
}

export function interventionLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    ask_followup: '继续提出区分性追问',
    explain_concept: '提供针对性概念讲解',
    targeted_practice: '派发针对性练习',
    transfer_check: '派发独立迁移验证',
    schedule_review: '安排后续复习',
  };
  return value ? labels[value] ?? '服务端返回了其他后续动作' : '服务端尚未选择干预';
}
