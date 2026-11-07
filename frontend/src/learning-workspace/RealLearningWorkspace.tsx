import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiClientError, type AsyncResourceState } from '../api/client';
import {
  completeSession,
  createSession,
  dispatchTransferCheck,
  getSession,
  getTopic,
  getTopicMaterials,
  listSessionAttempts,
  listSessions,
  listTopics,
  submitAttempt,
} from '../api';
import type {
  AttemptResult,
  AttemptSummary,
  LearningMaterial,
  SanitizedQuestion,
  SessionDetail,
  SessionSummary,
  TopicDetail,
  TopicSummary,
} from '../api/types';
import type { WorkspaceId } from '../app-shell/navigation';
import { deriveLearningVisualStage, describeNextAction, prepareAttemptIntent, restoreSessionFromServer, SingleFlightGate, type PendingAttemptIntent } from './learningFlow';
import { useApiResource } from './useApiResource';

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
  const topicLoader = useCallback(
    (signal: AbortSignal) => selectedTopicId ? getTopic(selectedTopicId, signal) : Promise.resolve(null),
    [selectedTopicId],
  );
  const materialsLoader = useCallback(
    (signal: AbortSignal) => selectedTopicId ? getTopicMaterials(selectedTopicId, signal) : Promise.resolve([]),
    [selectedTopicId],
  );
  const topicResource = useApiResource<TopicDetail | null>(topicLoader);
  const materialsResource = useApiResource<LearningMaterial[]>(materialsLoader);

  const [session, setSession] = useState<SessionDetail | null>(null);
  const [attempts, setAttempts] = useState<AttemptSummary[]>([]);
  const [draft, setDraft] = useState('');
  const [attemptResult, setAttemptResult] = useState<AttemptResult | null>(null);
  const [pendingAttempt, setPendingAttempt] = useState<PendingAttemptIntent | null>(null);
  const [operation, setOperation] = useState<OperationState>({ kind: 'idle' });
  const [sessionLoadError, setSessionLoadError] = useState<unknown>(null);
  const [didRecoverPointer, setDidRecoverPointer] = useState(false);
  const operationGate = useRef(new SingleFlightGate());
  const operationController = useRef<AbortController | null>(null);

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
      const created = await createSession({ topic_id: selectedTopicId, learner_id: LEARNER_ID }, signal);
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
    setAttemptResult(null);
    setPendingAttempt(null);
    setDraft('');
    setSessionLoadError(null);
    window.sessionStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, resumed.id);
  });

  const submitPreparedAttempt = async (reusePending: boolean) => {
    if (!session || !activeQuestion || operationGate.current.isActive) return;
    const answer = draft.trim();
    if (!reusePending && !answer) return;

    let prepared: PendingAttemptIntent;
    try {
      prepared = prepareAttemptIntent(pendingAttempt, session.id, activeQuestion.id, answer, reusePending);
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
      if (draft.trim() === submitted.payload.submitted_answer) setDraft('');
      try {
        await refreshSession(submitted.sessionId, signal);
        void sessionsResource.retry();
      } catch (syncError) {
        setSessionLoadError(syncError);
      }
    });
    if (!succeeded && pendingAttempt?.payload.idempotency_key !== submitted.payload.idempotency_key) {
      setPendingAttempt(submitted);
    }
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
  const nextAction = attemptResult ? describeNextAction(attemptResult.next_action) : null;
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
    if (operation.kind === 'idle') return null;
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
        {pendingAttempt && <button type="button" className="wb-btn sm" onClick={() => setPendingAttempt(null)}>保留草稿并重新编辑</button>}
      </div>
    );
  };

  if (workspace === 'home') {
    return (
      <div className="wb-grid">
        <main>
          <header className="wb-page-heading">
            <div className="wb-eyebrow">REAL LEARNING · REST API</div>
            <h1>选择知识点，开始一次真实学习</h1>
            <p>下方目录、材料、会话和题目均来自 FastAPI 响应。此模式不会在请求失败时回退到演示数据。</p>
          </header>
          {sessionLoadError !== null && <div role="alert" className="wb-alert danger">恢复上次会话失败 · {getErrorView(sessionLoadError).code}：{getErrorView(sessionLoadError).message}</div>}
          {!didRecoverPointer && <div role="status" className="wb-alert info">正在检查本机保存的会话 ID…</div>}
          {session && <section className="wb-card"><div className="wb-card-head"><h2 className="wb-card-title">{session.status === 'completed' ? '最近会话已结束：' : '正在学习：'}{session.topic_title}</h2><StateBadge label="会话" value={session.status} /></div><div className="wb-card-body"><p>会话 ID：<code>{session.id}</code></p><button className="wb-btn primary" onClick={() => onNavigateWorkspace('learning')}>{session.status === 'completed' ? '查看会话结果' : '继续当前会话'}</button></div></section>}
          <section className="wb-card">
            <div className="wb-card-head"><h2 className="wb-card-title">可学习知识点</h2><span className="wb-badge blue">GET /api/v1/topics</span></div>
            <div className="wb-card-body">
              <ResourceNotice state={topicsResource.state} emptyMessage="服务端当前没有可用知识点。" onRetry={() => void topicsResource.retry()} />
              {topicsResource.state.status === 'success' && <div className="wb-topic-list">{topicsResource.state.data.map((topic) => (
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
          <section className="wb-card"><div className="wb-card-head"><h2 className="wb-card-title">历史学习会话</h2><span className="wb-badge slate">GET /api/v1/sessions</span></div><div className="wb-card-body">
            <ResourceNotice state={sessionsResource.state} emptyMessage="尚无历史会话。选择知识点即可开始。" onRetry={() => void sessionsResource.retry()} />
            {sessionsResource.state.status === 'success' && sessionsResource.state.data.map((item) => <div className="wb-session-row" key={item.id}><div><strong>{item.topic_title}</strong><div><code>{item.id}</code> · {item.status} · {item.attempts_count} 次作答</div></div><button className="wb-btn sm" disabled={operation.kind === 'loading'} onClick={() => void restoreSelectedSession(item)}>{item.status === 'paused' ? '恢复会话' : item.status === 'completed' ? '查看会话' : '打开会话'}</button></div>)}
          </div></section>
        </main>
        <Inspector session={session} question={session?.current_question ?? null} attempt={attemptResult} />
        {renderOperation()}
      </div>
    );
  }

  if (workspace === 'learning') {
    const submittedQuestionAlreadyCurrent = activeQuestion === null && Boolean(session?.current_question);
    return (
      <div className="wb-grid">
        <main>
          <header className="wb-page-heading"><div className="wb-eyebrow">REAL SESSION WORKSPACE</div><h1>学习工作区</h1><p>题目内容来自当前服务端会话。诊断、干预或迁移只根据服务端动作提示展示。</p></header>
          {!session && <section className="wb-card"><div className="wb-card-body"><p>尚未选择学习会话。请从学习主页创建新会话或恢复历史会话。</p><button className="wb-btn primary" onClick={() => onNavigateWorkspace('home')}>选择知识点与会话</button></div></section>}
          {session && <>
            <section className="wb-card"><div className="wb-card-head"><h2 className="wb-card-title">{session.topic_title}</h2><div className="wb-badge-row"><StateBadge label="SessionStatus" value={session.status} /><StateBadge label="KnowledgeMasteryStatus" value={session.knowledge_state_status ?? 'unknown'} /></div></div><div className="wb-card-body"><p>会话 <code>{session.id}</code></p>{session.topic_mastered && <div className="wb-alert success">服务端返回 topic_mastered=true。</div>}</div></section>
            {activeQuestion && session.status !== 'completed' ? <section className="wb-card"><div className="wb-card-head"><div><span className="wb-eyebrow">SERVER-ASSIGNED QUESTION</span><h2 className="wb-card-title">{activeQuestion.question_role} · {activeQuestion.question_type}</h2></div><span className="wb-badge blue">{activeQuestion.id} · v{activeQuestion.version}</span></div><div className="wb-card-body"><p>{activeQuestion.prompt_text}</p>{activeQuestion.context_snippet && <pre className="wb-code-block">{activeQuestion.context_snippet}</pre>}<label className="wb-field-label" htmlFor="real-answer">你的答案或推理过程</label><textarea id="real-answer" className="wb-textarea" maxLength={2000} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="输入答案；提交失败时草稿会保留。" disabled={operation.kind === 'loading'} />{draft.length > 1900 && <small>{draft.length}/2000</small>}<div className="wb-btn-group"><button type="button" className="wb-btn primary" disabled={!draft.trim() || operation.kind === 'loading' || sessionLoadError !== null} onClick={() => void submitPreparedAttempt(false)}>提交作答</button><button type="button" className="wb-btn" disabled={!draft} onClick={() => setDraft('')}>清空草稿</button></div></div></section> : <section className="wb-card"><div className="wb-card-body">{session.status === 'completed' ? <p>此会话已由服务端结束。</p> : submittedQuestionAlreadyCurrent ? <p>该题已有作答记录；等待服务端下一步或派发新题，不会重复显示为可作答题目。</p> : <p>当前会话暂无可作答题目。请查看服务端返回的下一步动作。</p>}</div></section>}
            {attemptResult && <section className="wb-card"><div className="wb-card-head"><h2 className="wb-card-title">服务端作答结果</h2><span className={`wb-badge ${attemptResult.is_correct === true ? 'green' : attemptResult.is_correct === false ? 'amber' : 'slate'}`}>{attemptResult.is_correct === true ? '正确' : attemptResult.is_correct === false ? '未通过' : '待判定'}</span></div><div className="wb-card-body"><p>Attempt ID：<code>{attemptResult.attempt_id}</code></p><p>{attemptResult.evaluation_summary ?? attemptResult.feedback_text ?? '服务端未返回评估说明。'}</p><p>next_action：<code>{attemptResult.next_action}</code></p>{attemptResult.diagnostic_case_id && <p>诊断案例：<code>{attemptResult.diagnostic_case_id}</code> · 等待 Agent 诊断界面接入；此处不会伪造假设或证据。</p>}{attemptResult.knowledge_state_status && <StateBadge label="KnowledgeMasteryStatus" value={attemptResult.knowledge_state_status} />}{nextAction && <div className={`wb-alert ${nextAction.tone}`}>{nextAction.title} · {nextAction.description}</div>}{attemptResult.next_question && attemptResult.next_question.id !== attemptResult.question_id && <div className="wb-alert info">服务端已返回下一题：<code>{attemptResult.next_question.id}</code>（{attemptResult.next_question.question_role}）。重新读取会话以同步当前题目。</div>}{attemptResult.next_action === 'transfer_check' && !activeQuestion && <button className="wb-btn primary" disabled={operation.kind === 'loading'} onClick={() => void dispatchNextTransfer()}>请求服务端派发迁移验证题</button>}{attemptResult.next_action === 'transfer_failed_needs_practice' && <button className="wb-btn" disabled={operation.kind === 'loading'} onClick={() => void dispatchNextTransfer()}>请求另一道服务端迁移验证题</button>}{attemptResult.next_action === 'transfer_retry_blocked' && <button className="wb-btn primary" disabled={operation.kind === 'loading'} onClick={() => void dispatchNextTransfer()}>请求未尝试过的迁移题</button>}</div></section>}
            {session.status !== 'completed' && <button type="button" className="wb-btn" disabled={operation.kind === 'loading'} onClick={() => void endSession()}>结束此会话</button>}
          </>}
          {sessionLoadError !== null && <div role="alert" className="wb-alert danger">刷新会话失败 · {getErrorView(sessionLoadError).code}: {getErrorView(sessionLoadError).message}<button type="button" className="wb-btn sm" disabled={operation.kind === 'loading'} onClick={retrySessionSync}>重试读取会话</button></div>}
          {renderOperation()}
        </main>
        <Inspector session={session} question={activeQuestion} attempt={attemptResult} />
      </div>
    );
  }

  const titles: Record<Exclude<WorkspaceId, 'home' | 'learning'>, string> = {
    diagnosis: '诊断工作区将在 Stage 5C.2 接入真实诊断 API。',
    transfer: '迁移验证使用真实服务端派题；请在学习工作区按 next_action 继续。',
    review: '复习队列将在后续阶段接入真实 Review API。',
    profile: '知识状态与档案将在后续阶段接入真实 Profile API。',
  };
  return <div className="wb-grid"><main><header className="wb-page-heading"><div className="wb-eyebrow">REAL API MODE · NO MOCK FALLBACK</div><h1>{titles[workspace as Exclude<WorkspaceId, 'home' | 'learning'>]}</h1><p>当前真实模式不会用本地演示数据填充此区域。</p></header>{session && <section className="wb-card"><div className="wb-card-body"><StateBadge label="SessionStatus" value={session.status} />{session.active_diagnostic_case_id && <p>服务端诊断案例 ID：<code>{session.active_diagnostic_case_id}</code>。诊断执行和假设/证据展示属于 Stage 5C.2。</p>}<button className="wb-btn primary" onClick={() => onNavigateWorkspace('learning')}>返回当前学习会话</button></div></section>}</main><Inspector session={session} question={session?.current_question ?? null} attempt={attemptResult} />{renderOperation()}</div>;
};

function Inspector({ session, question, attempt }: { session: SessionDetail | null; question: SanitizedQuestion | null; attempt: AttemptResult | null }) {
  return <aside className="wb-inspector" aria-label="服务端会话状态 Inspector"><section className="wb-card"><div className="wb-card-head"><div><span className="wb-eyebrow">SERVER STATE INSPECTOR</span><h2 className="wb-card-title">会话与下一步</h2></div><span className="wb-badge green">REAL API</span></div><div className="wb-card-body">{session ? <><StateBadge label="SessionStatus" value={session.status} /><StateBadge label="KnowledgeMasteryStatus" value={session.knowledge_state_status ?? 'unknown'} />{session.active_diagnostic_case_id && <p>DiagnosticCase ID：<code>{session.active_diagnostic_case_id}</code></p>}{question && <p>当前题目：<code>{question.id}</code> · {question.question_role}</p>}{attempt && <p>next_action：<code>{attempt.next_action}</code></p>}</> : <p>尚无活动会话。</p>}<p className="wb-muted-note">Inspector 展示服务端字段；此阶段不展示模拟决策时间线。</p></div></section></aside>;
}
