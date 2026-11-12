import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiClientError } from '../api/client';
import { learnerEvidenceValidityReason } from '../evidenceValidity';
import { createAttemptSubmission, getSessionMaterial, submitAttempt } from '../api/sessions';
import { getReview, listReviews, startReview } from '../api/reviews';
import { listLearningHistory } from '../api/profile';
import type { AttemptResult, LearningHistoryEvent, ReviewItem, StructuredAnswer, SubmitAttemptRequest } from '../api/types';
import { useApiResource } from '../learning-workspace/useApiResource';
import { questionTypeLabel } from '../learning-workspace/errorDna';
import { MatchingHeadingsQuestion, MatchingHeadingsResult } from '../learning-workspace/MatchingHeadingsQuestion';
import { headingGroup, readHeadingDraft, storeHeadingDraft, validHeadingSelections } from '../learning-workspace/matchingHeadings';
import { restoreAttemptPayload, SingleFlightGate } from '../learning-workspace/learningFlow';
import type { WorkspaceId } from '../app-shell/navigation';

const LEARNER_ID = 'default_learner';
const ACTIVE_REVIEW_KEY = 'unlearnloop.real.active-review.v1';
const PENDING_REVIEW_ANSWER_KEY = 'unlearnloop.real.pending-review-answer.v1';
const DRAFT_PREFIX = 'unlearnloop.real.review-draft.v1:';

interface PendingReviewAnswer {
  reviewId: string;
  sessionId: string;
  payload: Readonly<SubmitAttemptRequest>;
}

function readPendingAnswer(): PendingReviewAnswer | null {
  try {
    const value = window.sessionStorage.getItem(PENDING_REVIEW_ANSWER_KEY);
    if (!value) return null;
    const intent = JSON.parse(value) as PendingReviewAnswer;
    return { ...intent, payload: restoreAttemptPayload(intent.payload) };
  } catch {
    return null;
  }
}

function formatDate(value?: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return '时间暂不可用';
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(new Date(value));
}

function learnerReviewReason(item: ReviewItem): string {
  if (item.retention_eligible) return '这次复习会用新的作答，检查之前学到的内容是否仍能独立运用。';
  return '之前的学习证据提示还需要继续练习；本次不会被记作长期保持证明。';
}

function reviewResultFromItem(item: ReviewItem): AttemptResult | null {
  if (!item.attempt_id || item.is_correct === null || item.is_correct === undefined) return null;
  const passedRetention = item.retention_verified === true;
  const passedWithoutBaseline = item.review_outcome === 'passed_without_retention_baseline';
  const nextAction = item.review_outcome === 'failed'
    ? 'review_failed_needs_diagnosis'
    : passedRetention ? 'delayed_retention_verified'
      : passedWithoutBaseline ? 'review_passed_without_retention' : 'review_evaluated';
  return {
    attempt_id: item.attempt_id,
    session_id: item.review_session_id ?? '',
    question_id: item.question_id ?? '',
    question_role: 'review',
    is_correct: item.is_correct,
    evaluation_summary: item.evaluation_summary,
    feedback_text: item.evaluation_summary,
    next_action: nextAction,
    knowledge_state_status: undefined,
    group_evaluation: item.group_evaluation,
  };
}

export const FocusReviewWorkspace: React.FC<{
  onNavigateWorkspace: (workspace: WorkspaceId) => void;
}> = ({ onNavigateWorkspace }) => {
  const loadPending = useCallback((signal: AbortSignal) =>
    listReviews({ learner_id: LEARNER_ID, status: 'pending' }, signal), []);
  const loadHistory = useCallback((signal: AbortSignal) => listLearningHistory(LEARNER_ID, 100, signal), []);
  const pendingResource = useApiResource<ReviewItem[]>(loadPending);
  const historyResource = useApiResource<LearningHistoryEvent[]>(loadHistory);
  const [activeReview, setActiveReview] = useState<ReviewItem | null>(null);
  const [draft, setDraft] = useState('');
  const [headingDraft, setHeadingDraft] = useState<StructuredAnswer>({});
  const [pendingAnswer, setPendingAnswer] = useState<PendingReviewAnswer | null>(() => readPendingAnswer());
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const submitGate = useRef(new SingleFlightGate());

  const activeReviewId = activeReview?.id ?? null;
  const activeQuestion = activeReview?.status === 'pending' ? activeReview.current_question ?? null : null;
  const reviewSessionId = activeReview?.review_session_id;
  const groupQuestion = activeQuestion?.question_type === 'matching_headings';
  const loadMaterials = useCallback(async (signal: AbortSignal) => reviewSessionId && !groupQuestion ? [await getSessionMaterial(reviewSessionId, signal)].filter((item): item is NonNullable<typeof item> => item !== null) : [], [reviewSessionId, activeQuestion?.id, groupQuestion]);
  const materials = useApiResource(loadMaterials);
  const isPendingIntentForActive = pendingAnswer?.reviewId === activeReview?.id;
  const applyReview = useCallback((item: ReviewItem) => {
    const storage = window.sessionStorage;
    const intent = readPendingAnswer();
    const question = item.current_question;
    setActiveReview(item);
    setResult(reviewResultFromItem(item));
    if (intent?.reviewId === item.id && item.attempt_id) {
      storage.removeItem(PENDING_REVIEW_ANSWER_KEY);
      if (intent.payload.group_version_id) {
        storeHeadingDraft(storage, intent.sessionId, intent.payload.question_id, intent.payload.group_version_id, {});
      } else storage.removeItem(`${DRAFT_PREFIX}${item.id}`);
      setPendingAnswer(null);
      setDraft('');
      setHeadingDraft({});
      setInfo('已从服务端恢复这次复习评价，没有重复提交。');
      return;
    }
    const payload = intent?.reviewId === item.id ? intent.payload : undefined;
    setPendingAnswer(intent);
    setDraft(payload?.submitted_answer ?? storage.getItem(`${DRAFT_PREFIX}${item.id}`) ?? '');
    setHeadingDraft(payload?.structured_answer && payload.question_id === question?.id && payload.group_version_id === question.group_version_id
      ? { ...payload.structured_answer }
      : item.review_session_id ? readHeadingDraft(storage, item.review_session_id, question) : {});
    if (payload) setInfo('已读取服务端状态。尚未确认的作答可使用原请求安全恢复。');
  }, []);

  useEffect(() => {
    if (!activeReviewId) return;
    const controller = new AbortController();
    void getReview(activeReviewId, LEARNER_ID, controller.signal).then((item) => {
      if (controller.signal.aborted) return;
      applyReview(item);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取复习任务失败。');
    });
    return () => controller.abort();
  }, [activeReviewId, applyReview]);

  useEffect(() => {
    const intent = readPendingAnswer();
    const savedReviewId = intent?.reviewId ?? window.sessionStorage.getItem(ACTIVE_REVIEW_KEY);
    if (!savedReviewId) return;
    window.sessionStorage.setItem(ACTIVE_REVIEW_KEY, savedReviewId);
    setActiveReview((current) => current?.id === savedReviewId ? current : { id: savedReviewId } as ReviewItem);
  }, []);

  const orderedPending = useMemo(() => pendingResource.state.status === 'success'
    ? pendingResource.state.data : [], [pendingResource.state]);

  const beginReview = async (item: ReviewItem) => {
    const frozenIntent = readPendingAnswer();
    if (frozenIntent && frozenIntent.reviewId !== item.id) {
      setActiveReview({ id: frozenIntent.reviewId } as ReviewItem);
      window.sessionStorage.setItem(ACTIVE_REVIEW_KEY, frozenIntent.reviewId);
      setInfo('先恢复上一次尚未确认的作答；为避免丢失原幂等请求，暂不切换到另一项复习。');
      return;
    }
    setBusy(true); setError(null); setInfo(null); setResult(null);
    try {
      const started = await startReview(item.id, LEARNER_ID);
      applyReview(started);
      window.sessionStorage.setItem(ACTIVE_REVIEW_KEY, item.id);
      if (!started.current_question) setInfo(started.message ?? '目前没有可派发的独立复习题，任务仍保留待办。');
      await pendingResource.retry();
    } catch (reason) {
      setError(reason instanceof ApiClientError ? `${reason.code} · ${reason.message}` : reason instanceof Error ? reason.message : '开始复习失败。');
    } finally { setBusy(false); }
  };

  const refreshAuthoritativeReview = async (reviewId: string) => {
    const item = await getReview(reviewId, LEARNER_ID);
    applyReview(item);
    await pendingResource.retry();
  };

  const sendAnswer = async (retryExisting: boolean) => {
    if (!activeReview?.review_session_id || !activeQuestion || !activeReview.is_due || busy || submitGate.current.isActive) return;
    let intent = pendingAnswer;
    if (retryExisting && intent?.reviewId !== activeReview.id) return;
    if (!retryExisting) {
      if (intent?.reviewId === activeReview.id) return;
      const group = headingGroup(activeQuestion);
      const version = activeQuestion.group_version_id;
      const selections = group ? validHeadingSelections(group, headingDraft) : {};
      if (groupQuestion ? !group || !version || Object.keys(selections).length !== group.items.length : !draft.trim()) return;
      intent = {
        reviewId: activeReview.id,
        sessionId: activeReview.review_session_id,
        payload: createAttemptSubmission({ question_id: activeQuestion.id,
          ...(version ? { group_version_id: version, structured_answer: selections } : { submitted_answer: draft }),
        }),
      };
      window.sessionStorage.setItem(PENDING_REVIEW_ANSWER_KEY, JSON.stringify(intent));
      setPendingAnswer(intent);
    }
    if (!intent || !submitGate.current.tryAcquire()) return;
    setBusy(true); setError(null); setInfo(null);
    try {
      const attemptResult = await submitAttempt(intent.sessionId, intent.payload);
      setResult(attemptResult);
      const item = await getReview(intent.reviewId, LEARNER_ID);
      applyReview(item);
      setInfo('评价和复习状态已由服务端保存。');
      await pendingResource.retry();
    } catch (reason) {
      setError(reason instanceof ApiClientError ? `${reason.code} · ${reason.message}` : reason instanceof Error ? reason.message : '提交复习答案失败。');
      try {
        const item = await getReview(intent.reviewId, LEARNER_ID);
        applyReview(item);
        if (item.attempt_id) {
          setError(null);
          setInfo('服务端已经记录了这次作答，已恢复结果；没有再次提交。');
          await pendingResource.retry();
        }
      } catch {
        setInfo('无法确认服务器是否完成处理。保留原作答和幂等键，重新读取状态后再恢复。');
      }
    } finally { submitGate.current.release(); setBusy(false); }
  };

  const editPendingGroup = async () => {
    if (!activeReviewId || !pendingAnswer?.payload.group_version_id || busy) return;
    setBusy(true);
    try {
      const item = await getReview(activeReviewId, LEARNER_ID);
      applyReview(item);
      if (!item.attempt_id) {
        window.sessionStorage.removeItem(PENDING_REVIEW_ANSWER_KEY);
        setPendingAnswer(null);
        setInfo('已保留草稿，可以编辑后重新提交。');
      }
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法确认复习状态。');
    } finally { setBusy(false); }
  };

  const changeDraft = (value: string) => {
    setDraft(value);
    if (activeReview) window.sessionStorage.setItem(`${DRAFT_PREFIX}${activeReview.id}`, value);
  };

  const recoverActiveReview = async () => {
    const id = activeReview?.id ?? window.sessionStorage.getItem(ACTIVE_REVIEW_KEY);
    if (!id) return;
    setBusy(true); setError(null);
    try { await refreshAuthoritativeReview(id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取复习状态。'); }
    finally { setBusy(false); }
  };

  const continueDiagnosis = () => {
    if (!activeReview?.review_session_id) return;
    window.sessionStorage.setItem('unlearnloop.real.active-session.v1', activeReview.review_session_id);
    onNavigateWorkspace('diagnosis');
  };

  return <div className="focus-page focus-review-page">
    <div className="focus-page-content">
      <header className="focus-page-header">
        <div className="focus-eyebrow">间隔复习</div>
        <h1 className="focus-page-title">用一次新的作答，检查理解是否还在。</h1>
        <p className="focus-page-subtitle">任务时间和到期状态来自服务端。完成复习需要回答服务端派发的新题。</p>
      </header>

      {error && <div role="alert" className="focus-notice danger">{error}<button className="focus-button-quiet" onClick={() => void recoverActiveReview()}>重新读取服务端状态</button></div>}
      {info && <div role="status" className="focus-notice info">{info}</div>}

      {activeReview && <section className="focus-review-session" aria-labelledby="active-review-title">
        <div className="focus-review-session-heading">
          <div><div className="focus-eyebrow">{activeReview.topic_title}</div><h2 id="active-review-title">{activeReview.status === 'completed' ? '本次复习记录' : '当前复习'}</h2></div>
          <button type="button" className="focus-button-quiet" disabled={busy} onClick={() => void recoverActiveReview()}>重新读取</button>
        </div>
        {activeQuestion && <div className="focus-review-question">
          {groupQuestion && <MatchingHeadingsQuestion
            question={activeQuestion} selections={headingDraft}
            onChange={(selections) => {
              if (!reviewSessionId || !activeQuestion.group_version_id) return;
              setHeadingDraft(selections);
              storeHeadingDraft(window.sessionStorage, reviewSessionId, activeQuestion.id, activeQuestion.group_version_id, selections);
            }}
            onSubmit={() => void sendAnswer(false)} submitLabel="提交复习作答"
            focusId="review-answer" busy={busy} locked={!activeReview.is_due || isPendingIntentForActive}
          />}
          {!groupQuestion && <>
          {materials.state.status === 'loading' && <p role="status">正在读取本题材料…</p>}
          {materials.state.status === 'error' && <p role="alert">材料读取失败。<button onClick={() => void materials.retry()}>重试</button></p>}
          {materials.state.status === 'success' && materials.state.data.filter(material => material.id === activeQuestion.material_id).map(material => <article className="wb-material" key={material.id}><h3>{material.title}</h3><pre>{material.content_body}</pre></article>)}
            <div className="focus-review-meta">{questionTypeLabel(activeQuestion.question_type)} · 计划时间 {formatDate(activeReview.scheduled_for)}</div>
            <h3>{activeQuestion.prompt_text}</h3>
            {activeQuestion.context_snippet && <pre className="focus-code">{activeQuestion.context_snippet}</pre>}
            <label className="focus-field-label" htmlFor="review-answer">写下答案或推理过程</label>
            <textarea id="review-answer" className="focus-textarea" maxLength={2000} value={draft} onChange={(event) => changeDraft(event.target.value)} disabled={busy || Boolean(isPendingIntentForActive)} placeholder="写下你的思路；草稿会保留在当前浏览器会话中。" />
          </>}
            {isPendingIntentForActive && <p className="focus-help">有一条尚未确认结果的作答。为避免产生第二种作答意图，请恢复原请求或先读取服务端状态。</p>}
            <div className="focus-actions">
              {isPendingIntentForActive
                ? <button type="button" className="focus-button" disabled={busy} onClick={() => void sendAnswer(true)}>用原作答和幂等键恢复</button>
                : !groupQuestion && <button type="button" className="focus-button" disabled={!draft.trim() || busy || !activeReview.is_due} onClick={() => void sendAnswer(false)}>提交复习作答</button>}
              {groupQuestion && isPendingIntentForActive && <button type="button" className="focus-button-quiet" disabled={busy} onClick={() => void editPendingGroup()}>保留草稿并重新编辑</button>}
            </div>
            {!activeReview.is_due && <p className="focus-help">服务端尚未允许开始这项复习；页面不会提前提交。</p>}
        </div>}
        {activeReview.evidence_validity_status && activeReview.evidence_validity_status !== 'eligible' && <div role="status" className="focus-notice warning">
          <strong>{activeReview.evidence_validity_status === 'invalidated' ? '这条历史评分目前不作为保持证据' : '这条历史记录的题目版本仍待核实'}</strong>
          <p>原始作答和当时的评分仍保留为历史记录；当前学习状态不会把它当作有效的延迟保持验证。</p>
          <details><summary>查看核对说明</summary><p>{learnerEvidenceValidityReason(activeReview.evidence_validity_status, activeReview.evidence_validity_reason)}</p></details>
        </div>}
        {!activeQuestion && activeReview.status === 'pending' && <div className="focus-empty"><strong>当前没有可用的独立复习题。</strong><p>{activeReview.message ?? '证据不足，任务仍保留待办，不会记为复习通过。'}</p></div>}
        {!activeQuestion && activeReview.status !== 'pending' && <div className={`focus-notice ${activeReview.retention_verified ? 'success' : activeReview.review_outcome === 'failed' ? 'warning' : 'neutral'}`}>
              <strong>{activeReview.retention_verified ? '本次获得延迟保持证据' : activeReview.review_outcome === 'failed' ? '本次复习未通过' : activeReview.review_outcome === 'passed_without_retention_baseline' ? '答对了，但不构成延迟保持证据' : '本次评价已保存'}</strong>
              <p>{activeReview.evaluation_summary ?? result?.evaluation_summary ?? '服务端未提供评价说明。'}</p>
              {result && <MatchingHeadingsResult result={result} question={activeReview.review_question} />}
              {activeReview.retention_verified && <p>这是一次延迟复习证据，不代表已经证明长期保持。</p>}
              {activeReview.review_outcome === 'passed_without_retention_baseline' && <p>当前没有符合条件的迁移验证基线，因此服务端没有把这次正确作答记为保持通过。</p>}
              {activeReview.review_outcome === 'failed' && <><p>当前需要继续练习。</p><button className="focus-button" onClick={continueDiagnosis}>继续查看诊断</button></>}
              <p className="focus-review-meta">复习时间：{formatDate(activeReview.submitted_at)} · 计划时间：{formatDate(activeReview.scheduled_for)}</p>
        </div>}
        {activeReview.status === 'completed' && activeReview.retention_verified && pendingResource.state.status === 'success' && (() => {
          const next = pendingResource.state.data.find((item) => item.topic_id === activeReview.topic_id);
          return <div className="focus-notice neutral">{next ? `下一次复习计划：${formatDate(next.scheduled_for)}。` : '服务端目前没有返回下一次复习计划。'}</div>;
        })()}
        {result && activeReview.status === 'completed' && <details className="focus-disclosure"><summary>查看本次复习依据</summary><div className="focus-disclosure-content">服务端作答记录 <code>{result.attempt_id}</code> · 结果由当前复习题的评价生成。</div></details>}
      </section>}

      <section className="focus-page-section">
        <div className="focus-review-section-heading"><div><h2>待复习</h2><p>到期状态由服务端计算；未到期任务不会开放作答。</p></div><span className="focus-review-count">{pendingResource.state.status === 'success' ? pendingResource.state.data.length : '—'} 项</span></div>
        {pendingResource.state.status === 'loading' && <div role="status" className="focus-notice neutral">正在读取服务端复习任务…</div>}
        {pendingResource.state.status === 'error' && <div role="alert" className="focus-notice danger">复习任务读取失败。真实模式不会替换为演示记录。<button className="focus-button-quiet" onClick={() => void pendingResource.retry()}>重试</button></div>}
        {pendingResource.state.status === 'success' && orderedPending.length === 0 && <div className="focus-empty">目前没有待复习任务。新的计划会在服务端获得有效学习证据后生成。</div>}
        {pendingResource.state.status === 'success' && orderedPending.length > 0 && <div className="focus-review-list">
          {orderedPending.map((item) => <article key={item.id} className="focus-review-row">
            <div className="focus-review-row-copy"><div className="focus-review-topic">{item.topic_title}</div><div className="focus-review-date">计划时间：{formatDate(item.scheduled_for)} · {item.is_due ? '已到期' : '尚未到期'}</div><p>{learnerReviewReason(item)}</p><small>{item.review_stage ? `第 ${item.review_stage + 1} 次间隔检查` : '首次延迟复习'} · {item.retention_eligible ? '用于检查延迟保持' : '后续学习任务'}</small>{historyResource.state.status === 'success' && (() => { const previous = historyResource.state.data.find((event) => event.topic_id === item.topic_id && !['review_scheduled'].includes(event.kind)); return <div className="focus-review-previous">上次学习：{previous ? `${previous.title} · ${previous.summary}` : '暂无历史作答摘要。'}</div>; })()}</div>
            {item.question_unavailable ? <span className="focus-help">{item.message ?? '暂无符合条件的独立复习题。'}</span>
              : <button type="button" className={item.is_due ? 'focus-button' : 'focus-button-secondary'} disabled={!item.is_due || busy || Boolean(pendingAnswer && pendingAnswer.reviewId !== item.id)} onClick={() => void beginReview(item)}>{pendingAnswer && pendingAnswer.reviewId !== item.id ? '先恢复上次作答' : item.is_due ? '开始复习' : '尚未到期'}</button>}
          </article>)}
        </div>}
      </section>
      <div className="focus-actions"><button className="focus-button-quiet" onClick={() => onNavigateWorkspace('profile')}>查看学习档案</button><button className="focus-button-quiet" onClick={() => onNavigateWorkspace('home')}>返回首页</button></div>
    </div>
  </div>;
};
