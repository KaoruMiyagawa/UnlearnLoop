import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiClientError, type AsyncResourceState } from '../api/client';
import {
  completeSession,
  createSession,
  dispatchTransferCheck,
  getSession,
  getSessionMaterial,
  getTopic,
  listSessionAttempts,
  listSessions,
  listTopics,
  retryDiagnosticStep,
  runDiagnosticStep,
  submitAttempt,
} from '../api';
import type {
  AttemptResult,
  AttemptSummary,
  DiagnosticStepResponse,
  LearningMaterial,
  SanitizedQuestion,
  SessionDetail,
  SessionSummary,
  TopicDetail,
  TopicSummary,
} from '../api/types';
import type { WorkspaceId } from '../app-shell/navigation';
import { clearPendingAttempt, deriveLearningVisualStage, describeNextAction, prepareAttemptIntent, readPendingAttempt, restoreSessionFromServer, SingleFlightGate, storePendingAttempt, type PendingAttemptIntent } from './learningFlow';
import { getTransferPresentation } from './transferFlow';
import {
  canRetryDiagnosticStep,
  canRunDiagnosticStep,
  clearPendingDiagnosticIntent,
  diagnosticStatusLabel,
  diagnosticExecutionDescription,
  evidenceRelationLabel,
  evidenceSourceLabel,
  getOrCreateDiagnosticIntent,
  groupEvidenceByHypothesis,
  hypothesisStatusLabel,
  interventionLabel,
  loadDiagnosticWorkspace,
  readPendingDiagnosticIntent,
  type DiagnosticWorkspaceData,
  type PendingDiagnosticIntent,
} from './diagnosticFlow';
import { useApiResource } from './useApiResource';
import { ReviewHomeEntry } from '../review-workspace/ReviewHomeEntry';
import { getExamProfile } from '../api/exams';
import type { ExamPreparationProfile } from '../api/types';

const LEARNER_ID = 'default_learner';
const ACTIVE_SESSION_STORAGE_KEY = 'unlearnloop.real.active-session.v1';

interface RealLearningWorkspaceProps {
  workspace: WorkspaceId;
  onNavigateWorkspace: (workspace: WorkspaceId) => void;
  onVisualStageChange: (stage: 1 | 2 | 3 | 4 | 5 | 6, hasDiagnosis: boolean) => void;
}

type OperationState =
  | { kind: 'idle' }
  | { kind: 'loading'; label: string }
  | { kind: 'success'; label: string }
  | { kind: 'error'; label: string; error: unknown };

function getErrorView(error: unknown): { code: string; message: string; requestId?: string; retryable: boolean } {
  if (error instanceof ApiClientError) {
    return { code: error.code, message: error.message, requestId: error.requestId, retryable: error.retryable };
  }
  return { code: 'REQUEST_ERROR', message: error instanceof Error ? error.message : '请求失败。', retryable: false };
}

function ResourceNotice<T>({
  state,
  emptyMessage,
  onRetry,
}: {
  state: AsyncResourceState<T>;
  emptyMessage?: string;
  onRetry: () => void;
}) {
  if (state.status === 'loading') {
    return <div role="status" className="wb-alert info">正在从 UnlearnLoop API 加载…</div>;
  }
  if (state.status === 'error') {
    const error = getErrorView(state.error);
    return (
      <div role="alert" className="wb-alert danger">
        <strong>{error.code}</strong> · {error.message}
        {error.requestId && <div>Request ID: <code>{error.requestId}</code></div>}
        <button type="button" className="wb-btn sm" onClick={onRetry}>重试读取</button>
      </div>
    );
  }
  if (state.status === 'success' && emptyMessage && Array.isArray(state.data) && state.data.length === 0) {
    return <div className="wb-alert neutral">{emptyMessage}</div>;
  }
  return null;
}

function StateBadge({ label, value }: { label: string; value: string }) {
  return <span className="wb-badge slate">{label}：<code>{value}</code></span>;
}

export const RealLearningWorkspace: React.FC<RealLearningWorkspaceProps> = ({ workspace, onNavigateWorkspace, onVisualStageChange }) => {
  const loadTopics = useCallback((signal: AbortSignal) => listTopics({}, signal), []);
  const loadSessions = useCallback((signal: AbortSignal) => listSessions({ learner_id: LEARNER_ID }, signal), []);
  const topicsResource = useApiResource<TopicSummary[]>(loadTopics);
  const sessionsResource = useApiResource<SessionSummary[]>(loadSessions);

  const [selectedTopicId, setSelectedTopicId] = useState('');
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [examProfile, setExamProfile] = useState<ExamPreparationProfile | null>(null);
  const [examProfileError, setExamProfileError] = useState(false);
  useEffect(() => { const controller = new AbortController(); void getExamProfile(LEARNER_ID, controller.signal).then(setExamProfile).catch(() => { if (!controller.signal.aborted) setExamProfileError(true); }); return () => controller.abort(); }, []);
  const topicLoader = useCallback(
    (signal: AbortSignal) => workspace === 'home' && selectedTopicId ? getTopic(selectedTopicId, signal) : Promise.resolve(null),
    [selectedTopicId, workspace],
  );
  const materialsLoader = useCallback(
    async (signal: AbortSignal) => session?.id ? [await getSessionMaterial(session.id, signal)].filter((item): item is LearningMaterial => item !== null) : [],
    [session?.id, session?.current_question_id],
  );
  const topicResource = useApiResource<TopicDetail | null>(topicLoader);
  const materialsResource = useApiResource<LearningMaterial[]>(materialsLoader);

  const [attempts, setAttempts] = useState<AttemptSummary[]>([]);
  const [draft, setDraft] = useState('');
  const [attemptResult, setAttemptResult] = useState<AttemptResult | null>(null);
  const [pendingAttempt, setPendingAttempt] = useState<PendingAttemptIntent | null>(null);
  const [diagnosticStep, setDiagnosticStep] = useState<{ caseId: string; result: DiagnosticStepResponse } | null>(null);
  const [pendingDiagnosticIntent, setPendingDiagnosticIntent] = useState<PendingDiagnosticIntent | null>(null);
  const [operation, setOperation] = useState<OperationState>({ kind: 'idle' });
  const [sessionLoadError, setSessionLoadError] = useState<unknown>(null);
  const [didRecoverPointer, setDidRecoverPointer] = useState(false);
  const operationGate = useRef(new SingleFlightGate());
  const operationController = useRef<AbortController | null>(null);

  const diagnosticCaseId = session?.active_diagnostic_case_id ?? attemptResult?.diagnostic_case_id ?? null;
  const diagnosticLoader = useCallback(
    (signal: AbortSignal) => diagnosticCaseId
      ? loadDiagnosticWorkspace(diagnosticCaseId, signal)
      : Promise.resolve(null),
    [diagnosticCaseId],
  );
  const diagnosticResource = useApiResource<DiagnosticWorkspaceData | null>(diagnosticLoader);

  useEffect(() => {
    setPendingDiagnosticIntent(diagnosticCaseId
      ? readPendingDiagnosticIntent(window.sessionStorage, diagnosticCaseId)
      : null);
    setDiagnosticStep((current) => current?.caseId === diagnosticCaseId ? current : null);
  }, [diagnosticCaseId]);

  const runOperation = useCallback(async (
    label: string,
    action: (signal: AbortSignal) => Promise<void>,
  ): Promise<boolean> => {
    if (!operationGate.current.tryAcquire()) return false;
    const controller = new AbortController();
    operationController.current = controller;
    setOperation({ kind: 'loading', label });
    try {
      await action(controller.signal);
      if (!controller.signal.aborted) setOperation({ kind: 'success', label });
      return true;
    } catch (error) {
      setOperation({ kind: 'error', label, error });
      return false;
    } finally {
      if (operationController.current === controller) operationController.current = null;
      operationGate.current.release();
    }
  }, []);

  const refreshSession = useCallback(async (sessionId: string, signal?: AbortSignal) => {
    const [detail, history] = await Promise.all([
      getSession(sessionId, signal),
      listSessionAttempts(sessionId, signal),
    ]);
    setSession(detail);
    setAttempts(history);
    setAttemptResult(detail.latest_attempt_result ?? null);
    setSelectedTopicId(detail.topic_id);
    setSessionLoadError(null);
    window.sessionStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
  }, []);

  // A saved ID is only a pointer. The session is restored from the server and
  // any failure remains visible; no local fixture is substituted.
  useEffect(() => {
    const savedId = window.sessionStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!savedId) {
      setDidRecoverPointer(true);
      return;
    }
    const controller = new AbortController();
    void restoreSessionFromServer(savedId, controller.signal).then(({ session: detail, attempts: history }) => {
      setSession(detail);
      setAttempts(history);
      setAttemptResult(detail.latest_attempt_result ?? null);
      const pending = readPendingAttempt(window.sessionStorage, detail.id);
      setPendingAttempt(pending);
      if (pending && pending.payload.question_id === detail.current_question_id) setDraft(pending.payload.submitted_answer);
      setSelectedTopicId(detail.topic_id);
      setDidRecoverPointer(true);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setSessionLoadError(error);
      setDidRecoverPointer(true);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => () => operationController.current?.abort(), []);

  const activeQuestion = useMemo<SanitizedQuestion | null>(() => {
    const question = session?.current_question ?? null;
    if (!question) return null;
    return attempts.some((attempt) => attempt.question_id === question.id) ? null : question;
  }, [attemptResult, attempts, session]);

  const visualStage = deriveLearningVisualStage(session, attemptResult);
  useEffect(() => {
    onVisualStageChange(visualStage, Boolean(session?.active_diagnostic_case_id));
  }, [onVisualStageChange, session, visualStage]);

  const createLearningSession = async () => {
    if (!selectedTopicId) return;
    await runOperation('创建学习会话', async (signal) => {
      const selected = topicsResource.state.status === 'success' ? topicsResource.state.data.find(t => t.id === selectedTopicId || t.slug === selectedTopicId) : undefined;
      const examVariant = selected?.domain_code === 'ielts_academic' || selected?.domain_code === 'ielts_general_training' ? examProfile?.exam_variant : undefined;
      const created = await createSession({ topic_id: selectedTopicId, learner_id: LEARNER_ID, ...(examVariant ? { exam_variant: examVariant } : {}) }, signal);
      setSession(created);
      setAttempts([]);
      setAttemptResult(null);
      setPendingAttempt(null);
      setDraft('');
      setSessionLoadError(null);
      window.sessionStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, created.id);
      void sessionsResource.retry();
    });
  };

  const restoreSelectedSession = async (summary: SessionSummary) => runOperation('恢复学习会话', async (signal) => {
    const { session: resumed, attempts: history } = await restoreSessionFromServer(summary.id, signal);
    setSession(resumed);
    setAttempts(history);
    setSelectedTopicId(resumed.topic_id);
    setAttemptResult(resumed.latest_attempt_result ?? null);
    const pending = readPendingAttempt(window.sessionStorage, resumed.id);
    setPendingAttempt(pending);
    setDraft(pending && pending.payload.question_id === resumed.current_question_id ? pending.payload.submitted_answer : '');
    setSessionLoadError(null);
    window.sessionStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, resumed.id);
  });

  const submitPreparedAttempt = async (reusePending: boolean) => {
    if (!session || operationGate.current.isActive || (!reusePending && !activeQuestion)) return;
    if (reusePending && !pendingAttempt) return;
    const answer = draft.trim();
    if (!reusePending && !answer) return;

    let prepared: PendingAttemptIntent;
    try {
      prepared = reusePending && pendingAttempt?.sessionId === session.id
        ? pendingAttempt
        : prepareAttemptIntent(pendingAttempt, session.id, activeQuestion!.id, answer, reusePending);
      storePendingAttempt(window.sessionStorage, prepared);
    } catch (error) {
      setOperation({ kind: 'error', label: '作答内容已改变', error });
      return;
    }
    if (prepared !== pendingAttempt) setPendingAttempt(prepared);

    const submitted = prepared;
    const succeeded = await runOperation(reusePending ? '重试原作答提交' : '提交作答', async (signal) => {
      const result = await submitAttempt(submitted.sessionId, submitted.payload, signal);
      setAttemptResult(result);
      setPendingAttempt(null);
      clearPendingAttempt(window.sessionStorage, submitted.sessionId);
      setDiagnosticStep(null);
      if (draft.trim() === submitted.payload.submitted_answer) setDraft('');
      try {
        await refreshSession(submitted.sessionId, signal);
        if (diagnosticCaseId && result.diagnostic_case_id === diagnosticCaseId) await diagnosticResource.retry();
        void sessionsResource.retry();
      } catch (syncError) {
        setSessionLoadError(syncError);
      }
    });
    if (!succeeded && pendingAttempt?.payload.idempotency_key !== submitted.payload.idempotency_key) {
      setPendingAttempt(submitted);
    }
  };

  const executeDiagnosticAction = async (
    action: 'step' | 'retry',
    replayPending = false,
  ) => {
    // Do not create/persist a diagnostic intent when a different session action
    // (for example, answer submission) currently owns the shared operation gate.
    if (operationGate.current.isActive) return;
    const loaded = diagnosticResource.state.status === 'success'
      ? diagnosticResource.state.data
      : null;
    const diagnosis = loaded?.diagnosis ?? null;
    if (!session || !diagnosticCaseId || !diagnosis) return;

    if (!replayPending && action === 'step' && !canRunDiagnosticStep(session, diagnosis, attempts)) return;
    if (!replayPending && action === 'retry' && !canRetryDiagnosticStep(session, diagnosis)) return;

    let intent: PendingDiagnosticIntent;
    try {
      if (replayPending) {
        const pending = readPendingDiagnosticIntent(window.sessionStorage, diagnosticCaseId);
        if (!pending || pending.action !== action) {
          throw new Error('没有可恢复的同一诊断操作；请先刷新服务端诊断状态。');
        }
        intent = pending;
      } else {
        intent = getOrCreateDiagnosticIntent(window.sessionStorage, diagnosticCaseId, action);
      }
      setPendingDiagnosticIntent(intent);
    } catch (error) {
      setOperation({ kind: 'error', label: '准备诊断步骤失败', error });
      return;
    }

    const completed = await runOperation(
      action === 'retry' ? '请求服务端重试诊断' : '请求 Agent 执行诊断步骤',
      async (signal) => {
        const result = action === 'retry'
          ? await retryDiagnosticStep(diagnosticCaseId, intent.payload, signal)
          : await runDiagnosticStep(diagnosticCaseId, intent.payload, signal);
        setDiagnosticStep({ caseId: diagnosticCaseId, result });
        await Promise.all([
          refreshSession(session.id, signal),
          diagnosticResource.retry(),
        ]);
        void sessionsResource.retry();
      },
    );

    if (completed) {
      clearPendingDiagnosticIntent(window.sessionStorage, diagnosticCaseId);
      setPendingDiagnosticIntent(null);
    } else {
      // A timeout/abort may arrive after the server committed. Reconcile reads
      // only; replay remains an explicit action using this exact idempotency key.
      await Promise.allSettled([
        refreshSession(session.id),
        diagnosticResource.retry(),
      ]);
    }
  };

  const refreshDiagnosticState = async () => {
    if (!session) return;
    await runOperation('重新读取服务端诊断状态', async (signal) => {
      await Promise.all([
        refreshSession(session.id, signal),
        diagnosticResource.retry(),
      ]);
    });
  };

  const dispatchNextTransfer = async () => {
    if (!session) return;
    let resultMessage: string | null = null;
    const dispatched = await runOperation('请求服务端派发迁移验证题', async (signal) => {
      // A prior request may have reached the server even if its response timed
      // out. Read authoritative state first to avoid dispatching a second item.
      const latest = await getSession(session.id, signal);
      const history = await listSessionAttempts(session.id, signal);
      const assignedUnattemptedTransfer = latest.current_question?.question_role === 'transfer_check'
        && !history.some((attempt) => attempt.question_id === latest.current_question?.id);
      if (assignedUnattemptedTransfer) {
        setSession(latest);
        setAttempts(history);
        setSessionLoadError(null);
        resultMessage = `已恢复服务端派发的迁移题：${latest.current_question?.id}`;
        return;
      }
      const dispatch = await dispatchTransferCheck(session.id, { force_fresh: true }, signal);
      await refreshSession(session.id, signal);
      resultMessage = dispatch.degraded ? `服务端暂未派题：${dispatch.message}` : dispatch.message;
    });
    if (dispatched && resultMessage) setOperation({ kind: 'success', label: resultMessage });
  };

  const endSession = async () => {
    if (!session) return;
    await runOperation('结束学习会话', async (signal) => {
      const completed = await completeSession(session.id, undefined, signal);
      setSession(completed);
      window.sessionStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, completed.id);
      void sessionsResource.retry();
    });
  };

  const cancelCurrentOperation = () => operationController.current?.abort();
  const selectedTopic = topicsResource.state.status === 'success'
    ? topicsResource.state.data.find((topic) => topic.id === selectedTopicId || topic.slug === selectedTopicId)
    : undefined;
  const selectableTopics = topicsResource.state.status === 'success'
    ? topicsResource.state.data.filter(topic => examProfile?.selection_persisted && topic.domain_code === (examProfile.exam_variant === 'general_training' ? 'ielts_general_training' : 'ielts_academic') && topic.id.endsWith('-reading-english'))
    : [];
  const nextAction = attemptResult ? describeNextAction(attemptResult.next_action) : null;
  const activeDiagnosticStep = diagnosticStep?.caseId === diagnosticCaseId ? diagnosticStep.result : null;
  const diagnosticPanelProps: DiagnosticPanelProps = {
    resource: diagnosticResource.state,
    session,
    attempts,
    latestStep: activeDiagnosticStep,
    pendingIntent: pendingDiagnosticIntent?.caseId === diagnosticCaseId ? pendingDiagnosticIntent : null,
    busy: operation.kind === 'loading',
    onRunStep: () => void executeDiagnosticAction('step'),
    onRetryStep: () => void executeDiagnosticAction('retry'),
    onReplayPending: (action) => void executeDiagnosticAction(action, true),
    onRefresh: () => void refreshDiagnosticState(),
  };
  const canRetrySubmission = operation.kind === 'error'
    && getErrorView(operation.error).retryable
    && pendingAttempt?.sessionId === session?.id;
  const retrySessionSync = () => {
    if (!session) return;
    void runOperation('重新读取服务端会话', async (signal) => {
      await refreshSession(session.id, signal);
      setSessionLoadError(null);
    });
  };

  const renderOperation = () => {
    if (operation.kind === 'idle') return pendingAttempt ? <div role="status" className="wb-alert warning">保存着一次尚未确认结果的作答。恢复时会使用原题目、原答案和原幂等键。<button type="button" className="wb-btn sm" onClick={() => void submitPreparedAttempt(true)}>恢复上次作答结果</button></div> : null;
    if (operation.kind === 'loading') {
      return (
        <div role="status" className="wb-alert info">
          {operation.label}… <button type="button" className="wb-btn sm" onClick={cancelCurrentOperation}>取消请求</button>
        </div>
      );
    }
    if (operation.kind === 'success') return <div role="status" className="wb-alert success">{operation.label} · 服务端已响应</div>;
    const error = getErrorView(operation.error);
    return (
      <div role="alert" className="wb-alert danger">
        <strong>{operation.label}失败 · {error.code}</strong><div>{error.message}</div>
        {error.requestId && <div>Request ID: <code>{error.requestId}</code></div>}
        {error.code === 'REQUEST_TIMEOUT' && <div>请求超时。若这是作答请求，重试会复用原幂等键。</div>}
        {error.code === 'REQUEST_ABORTED' && <div>请求已取消；若服务器已处理作答，复用原幂等键可安全重试。</div>}
        {canRetrySubmission && <button type="button" className="wb-btn sm primary" onClick={() => void submitPreparedAttempt(true)}>用原载荷重试</button>}
        {pendingAttempt && <button type="button" className="wb-btn sm" onClick={() => { clearPendingAttempt(window.sessionStorage, pendingAttempt.sessionId); setPendingAttempt(null); }}>保留草稿并重新编辑</button>}
      </div>
    );
  };

  if (workspace === 'home') {
    return (
      <div className="focus-home-page">
        <main>
          <header className="focus-page-header">
            <div className="focus-eyebrow">LEARN AT YOUR PACE</div>
            <h1 className="focus-page-title">从一个问题开始，继续向前。</h1>
            <p className="focus-page-subtitle">选择你想学习的知识，UnlearnLoop 会根据你的作答安排下一步。</p>
          </header>
          <ReviewHomeEntry onNavigateWorkspace={onNavigateWorkspace} />
          {sessionLoadError !== null && <div role="alert" className="wb-alert danger">恢复上次会话失败 · {getErrorView(sessionLoadError).code}：{getErrorView(sessionLoadError).message}</div>}
          {!didRecoverPointer && <div role="status" className="wb-alert info">正在检查本机保存的会话 ID…</div>}
          {session && <section className="focus-card focus-continue-card"><div className="focus-continue-copy"><div className="focus-eyebrow">{session.status === 'completed' ? 'RECENT SESSION' : 'PICK UP WHERE YOU LEFT OFF'}</div><h2>{session.topic_title}</h2><p>{session.status === 'completed' ? '上次学习已结束，可以查看记录或开始新的学习。' : '你的学习进度已保存，可以从当前服务端会话继续。'}</p></div><button className="wb-btn primary" onClick={() => onNavigateWorkspace('learning')}>{session.status === 'completed' ? '查看学习记录' : '继续学习'}</button></section>}
          <section className="wb-card">
            <div className="wb-card-head"><h2 className="wb-card-title">选择学习主题</h2><span className="wb-muted-note">来自服务端知识目录</span></div>
            <div className="wb-card-body">
              <ResourceNotice state={topicsResource.state} emptyMessage="当前考试模式暂无可用阅读主题。" onRetry={() => void topicsResource.retry()} />
              {topicsResource.state.status === 'success' && <div className="wb-topic-list">{selectableTopics.map((topic) => (
                <button key={topic.id} type="button" className={`wb-topic-option ${selectedTopicId === topic.id ? 'selected' : ''}`} onClick={() => setSelectedTopicId(topic.id)}>
                  <strong>{topic.title}</strong><span>{topic.summary}</span><small>{topic.domain_code} · difficulty {topic.difficulty_level}</small>
                </button>
              ))}</div>}
            </div>
          </section>
          {selectedTopicId && <section className="wb-card">
            <div className="wb-card-head"><h2 className="wb-card-title">知识点材料</h2><span className="wb-badge slate">服务端内容</span></div>
            <div className="wb-card-body">
              <ResourceNotice state={topicResource.state} onRetry={() => void topicResource.retry()} />
              {topicResource.state.status === 'success' && topicResource.state.data && <p>{topicResource.state.data.summary}</p>}
              <ResourceNotice state={materialsResource.state} emptyMessage="该知识点目前没有可读材料。" onRetry={() => void materialsResource.retry()} />
              {materialsResource.state.status === 'success' && materialsResource.state.data.map((material) => <article className="wb-material" key={material.id}><h3>{material.title}</h3><p>{material.summary}</p><pre>{material.content_body}</pre></article>)}
              <button type="button" className="wb-btn primary" disabled={!selectedTopic || operation.kind === 'loading'} onClick={() => void createLearningSession()}>为此知识点创建会话</button>
            </div>
          </section>}
          <details className="focus-disclosure focus-history"><summary>查看过往学习会话</summary><div className="focus-disclosure-content">
            <ResourceNotice state={sessionsResource.state} emptyMessage="尚无历史会话。选择知识点即可开始。" onRetry={() => void sessionsResource.retry()} />
            {sessionsResource.state.status === 'success' && sessionsResource.state.data.map((item) => <div className="wb-session-row" key={item.id}><div><strong>{item.topic_title}</strong><div><code>{item.id}</code> · {item.status} · {item.attempts_count} 次作答</div></div><button className="wb-btn sm" disabled={operation.kind === 'loading'} onClick={() => void restoreSelectedSession(item)}>{item.status === 'paused' ? '恢复会话' : item.status === 'completed' ? '查看会话' : '打开会话'}</button></div>)}
          </div></details>
        </main>
        {renderOperation()}
      </div>
    );
  }

  if (workspace === 'learning') {
    const submittedQuestionAlreadyCurrent = activeQuestion === null && Boolean(session?.current_question);
    return (
      <div className="focus-learning-page">
        <main>
          <header className="focus-page-header"><div className="focus-eyebrow">{activeQuestion?.question_role === 'transfer_check' ? 'TRANSFER CHECK' : 'LEARNING SESSION'}</div><h1 className="focus-page-title">{activeQuestion?.question_role === 'transfer_check' ? '换个场景，试着运用。' : '专注理解当前问题。'}</h1><p className="focus-page-subtitle">题目与下一步均由当前服务端会话决定。</p></header>
          {!session && <section className="wb-card"><div className="wb-card-body">
            <h2>选择阅读任务</h2>
            {examProfileError && <p role="alert">无法读取考试模式，请检查后端连接并返回首页重试。</p>}
            <ResourceNotice state={topicsResource.state} emptyMessage="当前考试模式暂无阅读任务。" onRetry={() => void topicsResource.retry()} />
            {topicsResource.state.status === 'success' && selectableTopics.map(topic => <button key={topic.id} type="button" className={`wb-topic-option ${selectedTopicId === topic.id ? 'selected' : ''}`} onClick={() => setSelectedTopicId(topic.id)}><strong>{topic.title}</strong><span>{topic.summary}</span></button>)}
            {selectedTopic && <button type="button" className="wb-btn primary" disabled={operation.kind === 'loading' || !examProfile?.selection_persisted} onClick={() => void createLearningSession()}>开始阅读</button>}
            <details className="focus-disclosure"><summary>恢复历史会话</summary><div className="focus-disclosure-content"><ResourceNotice state={sessionsResource.state} emptyMessage="尚无历史会话。" onRetry={() => void sessionsResource.retry()} />{sessionsResource.state.status === 'success' && sessionsResource.state.data.map(item => <div className="wb-session-row" key={item.id}><span>{item.topic_title} · {item.exam_variant ?? '原有学习'} · {item.status}</span><button className="wb-btn sm" onClick={() => void restoreSelectedSession(item)}>打开会话</button></div>)}</div></details>
            {!examProfileError && examProfile && !examProfile.selection_persisted && <p>请先在首页保存考试模式。</p>}
            <button className="wb-btn" onClick={() => onNavigateWorkspace('home')}>返回首页</button>
          </div></section>}
          {session && <>
            <div className="focus-session-meta"><span>{session.topic_title}</span><span>{session.exam_variant ?? '原有学习'}</span><span className="focus-meta-separator">·</span><StateBadge label="学习状态" value={session.knowledge_state_status ?? 'unknown'} /><button type="button" className="wb-btn sm" disabled={Boolean(draft.trim()) || operation.kind === 'loading'} onClick={() => { setSession(null); setSelectedTopicId(''); setAttempts([]); setAttemptResult(null); window.sessionStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY); }}>选择其他阅读任务</button></div>
            <details className="focus-disclosure focus-learning-materials">
              <summary>查看相关学习材料</summary>
              <div className="focus-disclosure-content">
                <ResourceNotice state={materialsResource.state} emptyMessage="该知识点目前没有服务端学习材料。" onRetry={() => void materialsResource.retry()} />
                {materialsResource.state.status === 'success' && materialsResource.state.data.filter(material => !session.exam_variant || material.id === session.current_question?.material_id).map((material) => <article className="wb-material" key={material.id}><h3>{material.title}</h3><p>{material.summary}</p><pre>{material.content_body}</pre></article>)}
              </div>
            </details>
            {activeQuestion && session.status !== 'completed' ? <section className="wb-card focus-question-card"><div className="wb-card-body"><div className="focus-question-meta"><span className="focus-eyebrow">{activeQuestion.question_role} · {activeQuestion.question_type}</span><span className="wb-badge blue">服务端题目</span></div><h2 className="focus-question-prompt">{activeQuestion.prompt_text}</h2>{activeQuestion.context_snippet && <pre className="wb-code-block focus-code">{activeQuestion.context_snippet}</pre>}<label className="wb-field-label" htmlFor="real-answer">你的答案或推理过程</label><textarea id="real-answer" className="wb-textarea focus-textarea" maxLength={2000} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="写下你的思路。提交失败时，草稿会保留。" disabled={operation.kind === 'loading'} />{draft.length > 1900 && <small className="focus-char-count">{draft.length}/2000</small>}<div className="wb-btn-group"><button type="button" className="wb-btn primary focus-primary-action" disabled={!draft.trim() || operation.kind === 'loading' || sessionLoadError !== null} onClick={() => void submitPreparedAttempt(false)}>提交作答</button><button type="button" className="wb-btn" disabled={!draft} onClick={() => setDraft('')}>清空草稿</button></div></div></section> : <section className="wb-card"><div className="wb-card-body">{session.status === 'completed' ? <p>此会话已由服务端结束。</p> : submittedQuestionAlreadyCurrent ? <p>该题已有作答记录；等待服务端下一步或派发新题，不会重复显示为可作答题目。</p> : <p>当前会话暂无可作答题目。请查看服务端返回的下一步动作。</p>}</div></section>}
            {attemptResult && <section className="wb-card">
              <div className="wb-card-head"><h2 className="wb-card-title">最近一次作答评价</h2><span className={`wb-badge ${attemptResult.is_correct === true ? 'green' : attemptResult.is_correct === false ? 'amber' : 'slate'}`}>{attemptResult.is_correct === true ? '正确' : attemptResult.is_correct === false ? '未通过' : '待判定'}</span></div>
              <div className="wb-card-body">
                <p>{attemptResult.evaluation_summary ?? attemptResult.feedback_text ?? '服务端未返回评估说明。'}</p>
                {nextAction && (!activeQuestion || attemptResult.next_question?.id === activeQuestion.id) && <div className={`wb-alert ${nextAction.tone}`}>{nextAction.title} · {nextAction.description}</div>}
                {attemptResult.mastery_note && <p>{attemptResult.mastery_note}</p>}
                <details className="focus-disclosure"><summary>查看本次评价记录</summary><div className="focus-disclosure-content">Attempt <code>{attemptResult.attempt_id}</code> · next_action <code>{attemptResult.next_action}</code><p>评价来源：{attemptResult.evaluation_source ?? 'unknown'} · 诊断案例：{attemptResult.diagnostic_case_id ?? '无关联诊断'}</p>{attemptResult.knowledge_state_status && <StateBadge label="本次知识状态" value={attemptResult.knowledge_state_status} />}</div></details>
                {session.can_dispatch_transfer && !activeQuestion && <button className="wb-btn" disabled={operation.kind === 'loading'} onClick={() => void dispatchNextTransfer()}>请求服务端派发迁移验证题</button>}
                {activeQuestion?.question_role === 'transfer_check' && <button className="wb-btn" onClick={() => onNavigateWorkspace('transfer')}>进入独立迁移验证</button>}
              </div>
            </section>}
            {diagnosticCaseId && <DiagnosticPanel {...diagnosticPanelProps} />}
            {session.status !== 'completed' && <button type="button" className="wb-btn" disabled={operation.kind === 'loading'} onClick={() => void endSession()}>结束此会话</button>}
          </>}
          {sessionLoadError !== null && <div role="alert" className="wb-alert danger">刷新会话失败 · {getErrorView(sessionLoadError).code}: {getErrorView(sessionLoadError).message}<button type="button" className="wb-btn sm" disabled={operation.kind === 'loading'} onClick={retrySessionSync}>重试读取会话</button></div>}
          {renderOperation()}
        </main>
      </div>
    );
  }

  if (workspace === 'transfer') {
    const transfer = getTransferPresentation(session, attempts, attemptResult);
    const transferQuestion = transfer.question;
    return <div className="focus-learning-page"><main>
      <header className="focus-page-header"><div className="focus-eyebrow">TRANSFER CHECK</div><h1 className="focus-page-title">把理解带到新的情境。</h1><p className="focus-page-subtitle">只有服务端派发的迁移题会显示在这里；本页面不会自行推定掌握状态。</p></header>
      {!session && <section className="wb-card"><div className="wb-card-body"><p>当前没有可恢复的学习会话。</p><button className="wb-btn primary" onClick={() => onNavigateWorkspace('home')}>返回首页</button></div></section>}
      {session && !transferQuestion && <section className="wb-card"><div className="wb-card-body"><p>{session.status === 'completed' ? '本次会话已结束。' : transfer.passed ? '本次独立迁移验证已通过。' : session.current_question?.question_role === 'transfer_check' ? '当前迁移题已评价；请根据服务端结果继续。' : '当前没有待作答的服务端迁移题，请按学习决策继续。'}</p><button className="wb-btn" onClick={() => onNavigateWorkspace('learning')}>查看当前学习任务</button></div></section>}
      {transferQuestion && <section className="wb-card focus-question-card"><div className="wb-card-body"><div className="focus-eyebrow">SERVER-ASSIGNED · {transferQuestion.question_type}</div>{materialsResource.state.status === 'success' && materialsResource.state.data.filter(material => material.id === transferQuestion.material_id).map(material => <article className="wb-material" key={material.id}><h3>{material.title}</h3><pre>{material.content_body}</pre></article>)}<ResourceNotice state={materialsResource.state} onRetry={() => void materialsResource.retry()} /><h2>{transferQuestion.prompt_text}</h2>{transferQuestion.context_snippet && <pre className="wb-code-block">{transferQuestion.context_snippet}</pre>}<label className="wb-field-label" htmlFor="transfer-answer">写下你的答案或推理过程</label><textarea id="transfer-answer" className="wb-textarea focus-textarea" maxLength={2000} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="写下你的思路。提交失败时，草稿会保留。" disabled={operation.kind === 'loading'} />{draft.length > 1900 && <small>{draft.length}/2000</small>}<div className="wb-btn-group"><button type="button" className="wb-btn primary" disabled={!draft.trim() || operation.kind === 'loading' || sessionLoadError !== null} onClick={() => void submitPreparedAttempt(false)}>提交迁移验证</button>{pendingAttempt && <button type="button" className="wb-btn" onClick={() => void submitPreparedAttempt(true)}>用原请求重试</button>}</div></div></section>}
      {transfer.result && <section className="wb-card"><div className="wb-card-body"><h2>{transfer.passed ? '本次独立迁移验证通过' : '最近一次迁移评价'}</h2><p>{transfer.result.evaluation_summary ?? transfer.result.feedback_text ?? '服务端未返回评估说明。'}</p><p>该次评价后的建议：{describeNextAction(transfer.result.next_action).title}</p><p>{transfer.result.mastery_note ?? '本次题目结果不能证明长期保持。'}</p><small>评价来源：{transfer.result.evaluation_source ?? 'unknown'} · 诊断案例：{transfer.result.diagnostic_case_id ?? '无关联诊断'}</small></div></section>}
      {transfer.canDispatch && <button className="wb-btn primary" disabled={operation.kind === 'loading'} onClick={() => void dispatchNextTransfer()}>请求服务端派发新的迁移题</button>}
      {session && <div className="wb-btn-group"><button className="wb-btn" onClick={() => onNavigateWorkspace('learning')}>返回学习与诊断</button>{session.status === 'transfer_checking' && <button className="wb-btn" disabled={operation.kind === 'loading'} onClick={() => void endSession()}>结束本次学习</button>}</div>}
      {sessionLoadError !== null && <div role="alert" className="wb-alert danger">读取会话失败：{getErrorView(sessionLoadError).message}<button className="wb-btn sm" onClick={retrySessionSync}>重新读取服务端状态</button></div>}
      {renderOperation()}
    </main></div>;
  }

  const titles: Record<Exclude<WorkspaceId, 'home' | 'learning'>, string> = {
    diagnosis: 'Agent 诊断检视器 · 服务端证据与下一步',
    transfer: '迁移验证使用服务端派发题目。',
    review: '复习队列将在后续阶段接入真实 Review API。',
    profile: '知识状态与档案将在后续阶段接入真实 Profile API。',
  };
  return <div className="focus-learning-page"><main><header className="focus-page-header"><div className="focus-eyebrow">REAL API · NO MOCK FALLBACK</div><h1 className="focus-page-title">{titles[workspace as Exclude<WorkspaceId, 'home' | 'learning'>]}</h1><p className="focus-page-subtitle">{workspace === 'diagnosis' ? '案例、假设和证据由诊断 API 提供；每次 Agent 步骤都由服务端决策。' : '当前真实模式不会用本地演示数据填充此区域。'}</p></header>{session && <section className="wb-card"><div className="wb-card-body"><StateBadge label="SessionStatus" value={session.status} />{session.active_diagnostic_case_id && <p>服务端诊断案例 ID：<code>{session.active_diagnostic_case_id}</code></p>}{workspace === 'diagnosis' && <DiagnosticPanel {...diagnosticPanelProps} />}<button className="wb-btn primary" onClick={() => onNavigateWorkspace('learning')}>返回当前学习会话</button></div></section>}{!session && workspace === 'diagnosis' && <section className="wb-card"><div className="wb-card-body"><p>当前没有已恢复的学习会话。请从学习主页创建或恢复会话。</p><button className="wb-btn primary" onClick={() => onNavigateWorkspace('home')}>前往学习主页</button></div></section>}{renderOperation()}</main></div>;
};

interface DiagnosticPanelProps {
  resource: AsyncResourceState<DiagnosticWorkspaceData | null>;
  session: SessionDetail | null;
  attempts: AttemptSummary[];
  latestStep: DiagnosticStepResponse | null;
  pendingIntent: PendingDiagnosticIntent | null;
  busy: boolean;
  onRunStep: () => void;
  onRetryStep: () => void;
  onReplayPending: (action: 'step' | 'retry') => void;
  onRefresh: () => void;
}

function DiagnosticDecisionCard({ result }: { result: DiagnosticStepResponse }) {
  const execution = diagnosticExecutionDescription(result, result);
  return <section className="wb-card" aria-label="最近一次服务端 Agent 决策"><div className="wb-card-head"><h2 className="wb-card-title">最近一次服务端 Agent 决策</h2><span className="wb-badge blue">{result.case_status}</span></div><div className="wb-card-body"><p>{interventionLabel(result.selected_intervention)}</p>{result.explanation_text && <div className="wb-alert info">{result.explanation_text}</div>}{result.next_question && <p>服务端派发题目：<code>{result.next_question.id}</code> · {result.next_question.question_role}</p>}{result.uncertainty_note && <p>{result.uncertainty_note}</p>}{result.degraded_mode && <div className="wb-alert warning">服务端已进入降级模式：{result.degradation_reason ?? '未提供原因'}</div>}<p>置信度解释：confidence_is_heuristic = {String(result.confidence_is_heuristic)}（启发式工作权重，不是统计概率）。模型运行：{execution.kind === 'unknown' ? 'unknown' : execution.kind === 'mock' ? 'FakeModelProvider · Mock' : `${execution.provider} · Live`}。</p></div></section>;
}

function DiagnosticPanel({
  resource,
  session,
  attempts,
  latestStep,
  pendingIntent,
  busy,
  onRunStep,
  onRetryStep,
  onReplayPending,
  onRefresh,
}: DiagnosticPanelProps) {
  if (resource.status === 'idle' || resource.status === 'loading') return <section className="wb-card"><div className="wb-card-body" role="status">正在从诊断 API 加载当前案例…</div></section>;
  if (resource.status === 'error') {
    const error = getErrorView(resource.error);
    return <section className="wb-card"><div className="wb-card-body"><div role="alert" className="wb-alert danger">{error.code} · {error.message}</div><button className="wb-btn sm" type="button" onClick={onRefresh}>重新读取服务端状态</button></div></section>;
  }
  if (resource.status !== 'success') return null;
  const data = resource.data;
  if (!data) return <section className="wb-card"><div className="wb-card-body"><p>{session?.active_diagnostic_case_id ? '正在恢复诊断案例…' : '当前会话没有活动诊断案例。'}</p></div></section>;

  const { diagnosis, hypotheses, evidence, triggerAttempt } = data;
  const groupedEvidence = groupEvidenceByHypothesis(evidence);
  const execution = diagnosticExecutionDescription(diagnosis, latestStep);
  const canStep = canRunDiagnosticStep(session, diagnosis, attempts);
  const canRetry = canRetryDiagnosticStep(session, diagnosis);

  const leadHypothesis = hypotheses[0];
  const currentSuggestion = latestStep?.explanation_text
    ?? latestStep?.uncertainty_note
    ?? diagnosis.uncertainty_note
    ?? (hypotheses.length > 0 ? '当前存在多个候选解释；继续收集证据后再判断。' : '服务端尚未提供足够证据来提出解释。');

  return <section className="wb-card wb-diagnostic-panel focus-diagnostic" aria-label="真实 Agent 诊断">
    <div className="wb-card-body">
      <div className="focus-diagnostic-heading"><div><div className="focus-eyebrow">A CLOSER LOOK</div><h2>正在理解这次作答</h2></div><span className={`wb-badge ${execution.kind === 'mock' ? 'purple' : execution.kind === 'live' ? 'green' : 'slate'}`}>{execution.kind === 'mock' ? '离线模拟模型' : execution.kind === 'live' ? 'Live Model' : '模型来源未知'}</span></div>
      {leadHypothesis && <p className="focus-diagnostic-lead">当前可能的问题：<strong>{leadHypothesis.name}</strong>。这是待验证的假设，不是确定结论。</p>}
      {!leadHypothesis && <p className="focus-diagnostic-lead">当前还不能确定问题原因。</p>}
      <p className="focus-diagnostic-explanation">{currentSuggestion}</p>
      {latestStep?.selected_intervention && <div className="focus-next-suggestion"><span>下一步建议</span><strong>{interventionLabel(latestStep.selected_intervention)}</strong>{latestStep.next_question && <p>服务端已派发一道新问题，当前会话会在下方显示。</p>}</div>}
      <div className="focus-diagnostic-status"><StateBadge label="诊断状态" value={diagnosis.status} /><StateBadge label="不确定性" value={diagnosis.uncertainty_level} /></div>
      {hypotheses.some((hypothesis) => hypothesis.missing_evidence_desc) && <p className="wb-muted-note">仍待区分：{hypotheses.filter((hypothesis) => hypothesis.missing_evidence_desc).map((hypothesis) => hypothesis.missing_evidence_desc).join('；')}</p>}

      <details className="focus-disclosure focus-evidence-disclosure">
        <summary>查看判断依据与其他可能性 <span>({hypotheses.length} 个假设 · {evidence.length} 条证据)</span></summary>
        <div className="focus-disclosure-content">
          <p className="wb-muted-note">启发式权重仅表示系统当前的相对工作判断。confidence_is_heuristic = true；它不是统计概率，也不代表诊断确定性。</p>
          <section className="wb-diagnostic-original"><h3>触发诊断的原始作答</h3><p>题目 ID：<code>{triggerAttempt.question_id}</code> · Attempt <code>{triggerAttempt.id}</code></p><blockquote>{triggerAttempt.submitted_answer}</blockquote></section>
          {hypotheses.length === 0 ? <p className="wb-alert neutral">服务端尚未生成候选假设；当前保留证据不足状态，不补入演示假设。</p> : hypotheses.map((hypothesis) => {
            const linked = groupedEvidence.get(hypothesis.id) ?? [];
            return <article className="wb-diagnostic-hypothesis" key={hypothesis.id}>
              <div className="wb-session-row"><strong>{hypothesis.name}</strong><span className="wb-badge slate">{hypothesisStatusLabel(hypothesis.status)}</span></div>
              {hypothesis.description && <p>{hypothesis.description}</p>}
              <p className="wb-confidence">启发式工作权重：{Math.round(hypothesis.confidence * 100)}% · confidence_is_heuristic = true</p>
              {hypothesis.missing_evidence_desc && <p className="wb-alert warning">尚待区分：{hypothesis.missing_evidence_desc}</p>}
              {linked.length === 0 ? <p className="wb-muted-note">当前没有与此假设关联的服务端证据。</p> : <ul className="wb-evidence-list">{linked.map((item) => <li className="wb-evidence-row" key={item.id}><span className={`wb-badge ${item.relation === 'supports' ? 'green' : item.relation === 'contradicts' ? 'amber' : 'slate'}`}>{evidenceRelationLabel(item.relation)}</span><span>{item.summary}</span><small>来源：{evidenceSourceLabel(item.source_type)} · <code>{item.source_ref}</code>{item.attempt_id ? ` · Attempt ${item.attempt_id}` : ''}{item.reliability_note ? ` · ${item.reliability_note}` : ''}</small></li>)}</ul>}
            </article>;
          })}
          <p className="wb-muted-note">诊断案例：<code>{diagnosis.id}</code> · {diagnosticStatusLabel(diagnosis.status)} · 追问 {diagnosis.followup_turn_count} 次 · 模型 {execution.provider} · tokens {diagnosis.tokens_used}{latestStep ? ` / ${latestStep.session_token_budget}` : ''}</p>
          {latestStep ? <DiagnosticDecisionCard result={latestStep} /> : <p className="wb-muted-note">这里只显示当前 API 状态；刷新后不会把缺失的决策历史伪装成完整时间线。</p>}
        </div>
      </details>

      <div className="wb-diagnostic-controls">
        {pendingIntent ? <><div role="status" className="wb-alert warning">有一个可能已到达服务端的诊断请求。先刷新状态；如需取回步骤结果，可使用原幂等键显式重放。</div><button type="button" className="wb-btn primary" disabled={busy} onClick={() => onReplayPending(pendingIntent.action)}>以原幂等键恢复上次{pendingIntent.action === 'retry' ? '重试' : '诊断步骤'}</button></> : canRetry ? <button type="button" className="wb-btn primary" disabled={busy} onClick={onRetryStep}>请求服务端重试诊断</button> : canStep ? <button type="button" className="wb-btn primary" disabled={busy} onClick={onRunStep}>请求 Agent 执行下一诊断步骤</button> : <p className="wb-alert neutral">当前服务端诊断状态不允许继续执行步骤。</p>}
        <button type="button" className="wb-btn sm" disabled={busy} onClick={onRefresh}>重新读取诊断与会话状态</button>
      </div>
    </div>
  </section>;
}
