import { ApiClientError } from '../api/client.ts';
import { createAttemptSubmission, getSession, listSessionAttempts, resumeSession } from '../api/sessions.ts';
import type { AttemptResult, AttemptSummary, SessionDetail, SubmitAttemptRequest } from '../api/types.ts';

export type LearningVisualStage = 1 | 2 | 3 | 4 | 5 | 6;

export interface NextActionPresentation {
  title: string;
  description: string;
  tone: 'neutral' | 'warning' | 'success';
}

export interface PendingAttemptIntent {
  sessionId: string;
  payload: Readonly<SubmitAttemptRequest>;
}

const pendingStorageKey = (sessionId: string) => `unlearnloop.real.pending-attempt.v1.${sessionId}`;

export function storePendingAttempt(storage: Pick<Storage, 'setItem'>, intent: PendingAttemptIntent): void {
  storage.setItem(pendingStorageKey(intent.sessionId), JSON.stringify(intent));
}

export function readPendingAttempt(storage: Pick<Storage, 'getItem'>, sessionId: string): PendingAttemptIntent | null {
  const raw = storage.getItem(pendingStorageKey(sessionId));
  if (!raw) return null;
  const intent = JSON.parse(raw) as PendingAttemptIntent;
  if (intent.sessionId !== sessionId || typeof intent.payload?.question_id !== 'string'
    || typeof intent.payload.submitted_answer !== 'string' || !intent.payload.idempotency_key) {
    throw new Error('保存的作答请求无效；请重新读取服务端状态。');
  }
  return { sessionId, payload: Object.freeze({ ...intent.payload }) };
}

export function clearPendingAttempt(storage: Pick<Storage, 'removeItem'>, sessionId: string): void {
  storage.removeItem(pendingStorageKey(sessionId));
}

/** Keeps a retry bound to its original answer and idempotency key. */
export function prepareAttemptIntent(
  pending: PendingAttemptIntent | null,
  sessionId: string,
  questionId: string,
  answer: string,
  retryOriginal = false,
): PendingAttemptIntent {
  if (pending?.sessionId === sessionId) {
    const matches = pending.payload.question_id === questionId
      && pending.payload.submitted_answer === answer;
    if (retryOriginal || matches) return pending;
    throw new ApiClientError(409, {
      code: 'PENDING_SUBMISSION_EXISTS',
      message: '请先重试原作答，或明确选择“重新编辑答案”后再创建新的提交意图。',
    });
  }
  return {
    sessionId,
    payload: createAttemptSubmission({ question_id: questionId, submitted_answer: answer }),
  };
}

/** Synchronous click guard shared by UI orchestration and its tests. */
export class SingleFlightGate {
  private active = false;

  get isActive(): boolean {
    return this.active;
  }

  tryAcquire(): boolean {
    if (this.active) return false;
    this.active = true;
    return true;
  }

  release(): void {
    this.active = false;
  }
}

export async function restoreSessionFromServer(
  sessionId: string,
  signal: AbortSignal,
): Promise<{ session: SessionDetail; attempts: AttemptSummary[] }> {
  const detail = await getSession(sessionId, signal);
  const [session, attempts] = await Promise.all([
    detail.status === 'paused' ? resumeSession(detail.id, undefined, signal) : Promise.resolve(detail),
    listSessionAttempts(sessionId, signal),
  ]);
  return { session, attempts };
}

/** This is presentation copy only. The action value remains server-owned. */
export function describeNextAction(action: string): NextActionPresentation {
  switch (action) {
    case 'continue':
      return { title: '继续当前学习', description: '请检查服务端当前派发的问题。', tone: 'neutral' };
    case 'diagnose':
      return { title: '等待诊断步骤', description: '服务端已创建诊断案例；本阶段不会在前端生成假设或证据。', tone: 'warning' };
    case 'diagnose_step':
      return { title: '需要继续诊断', description: '服务端要求继续收集证据或安排针对性干预。', tone: 'warning' };
    case 'transfer_check':
      return { title: '需要迁移验证题', description: '由服务端选择一题新的迁移验证题。', tone: 'neutral' };
    case 'transfer_failed_needs_practice':
      return { title: '迁移验证未通过', description: '掌握状态以服务端返回为准；可请求服务端派发下一道迁移题。', tone: 'warning' };
    case 'transfer_retry_blocked':
      return { title: '需要未尝试过的迁移题', description: '服务端没有将同题重答作为掌握证据。', tone: 'warning' };
    case 'mastery_achieved':
      return { title: '本次独立迁移验证通过', description: '当前验证通过不代表长期保持；会话仍需单独结束。', tone: 'success' };
    case 'transfer_unavailable':
      return { title: '独立迁移证据不足', description: '暂无未见过的新情境题。系统保留不确定性，不使用旧题确认掌握。', tone: 'warning' };
    case 'review_scheduled':
      return { title: '已安排复习', description: '当前操作结果由服务端返回。', tone: 'warning' };
    default:
      return { title: '收到服务端后续动作', description: `服务端返回：${action}。前端不会自行推断下一步。`, tone: 'neutral' };
  }
}

/** Six-step header is an informational map derived from server facts, never a workflow controller. */
export function deriveLearningVisualStage(
  session: SessionDetail | null,
  attempt: AttemptResult | null,
): LearningVisualStage {
  if (session?.topic_mastered || session?.knowledge_state_status === 'stable' || attempt?.next_action === 'mastery_achieved') {
    return 6;
  }

  if (session?.status === 'completed') {
    if (session.knowledge_state_status === 'needs_practice') return 5;
    if (session.knowledge_state_status === 'needs_diagnosis') return 3;
    return 1;
  }

  // A restored session may not have the previous AttemptResult in browser
  // memory. Keep the visual hint aligned with the server-owned session state.
  if (session?.status === 'diagnosing') return 3;

  const role = session?.current_question?.question_role ?? attempt?.next_question?.question_role;
  if (role === 'transfer_check' || attempt?.next_action === 'transfer_check' || attempt?.next_action === 'transfer_failed_needs_practice' || attempt?.next_action === 'transfer_retry_blocked') {
    return 5;
  }
  if (role === 'targeted_practice') return 4;
  if (session?.active_diagnostic_case_id && !session.current_question) return 3;
  if (role === 'diagnostic_followup' || attempt?.next_action === 'diagnose' || attempt?.next_action === 'diagnose_step') return 2;
  return 1;
}
