import { useCallback } from 'react';
import { listKnowledgeStates } from '../api/profile';
import { listReviews } from '../api/reviews';
import type { AsyncResourceState } from '../api/client';
import type { AttemptResult, AttemptSummary, DiagnosticStepResponse, SanitizedQuestion, SessionDetail } from '../api/types';
import { evidenceValidityLabel, learnerEvidenceValidityReason } from '../evidenceValidity';
import { DiagnosticInspectorRailFrame } from '../design-system/DiagnosticInspectorRail';
import {
  canRetryDiagnosticStep, canRunDiagnosticStep, diagnosticExecutionDescription, diagnosticStatusLabel,
  evidenceRelationLabel, evidenceSourceLabel, groupEvidenceByHypothesis, hypothesisStatusLabel,
  type DiagnosticWorkspaceData, type PendingDiagnosticIntent,
} from './diagnosticFlow';
import { evidenceTimeline, isVerifiedRetention, knowledgeStatusLabel, learnerDiagnosticText, reviewsForSession } from './errorDna';
import { useApiResource } from './useApiResource';
import './errorDna.css';

export interface ErrorDnaPanelProps {
  session: SessionDetail;
  attempts: AttemptSummary[];
  attemptResult: AttemptResult | null;
  activeQuestion: SanitizedQuestion | null;
  caseId: string | null;
  resource: AsyncResourceState<DiagnosticWorkspaceData | null>;
  latestStep: DiagnosticStepResponse | null;
  pendingIntent: PendingDiagnosticIntent | null;
  busy: boolean;
  sessionReadFailed: boolean;
  transferDispatchNotice: string | null;
  onRunStep: () => void;
  onRetryStep: () => void;
  onReplayPending: (action: 'step' | 'retry') => void;
  onRefresh: () => void;
  onAnswer: () => void;
  onDispatchTransfer: () => void;
  onReview: () => void;
}

const dateFormatter = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });

function formatDate(time?: string | null) {
  return time && Number.isFinite(Date.parse(time)) ? dateFormatter.format(new Date(time)) : '时间暂不可用';
}

export function ErrorDnaPanel({ session, attempts, attemptResult, activeQuestion, caseId, resource, latestStep,
  pendingIntent, busy, sessionReadFailed, transferDispatchNotice, onRunStep, onRetryStep, onReplayPending, onRefresh, onAnswer, onDispatchTransfer, onReview }: ErrorDnaPanelProps) {
  const { learner_id: learnerId, topic_id: topicId, updated_at: updatedAt } = session;
  const attemptId = attemptResult?.attempt_id;
  // Refresh read models after a server update. The session key isolates requests across sessions.
  const loadKnowledge = useCallback((signal: AbortSignal) => listKnowledgeStates(learnerId, signal), [learnerId, updatedAt, attemptId]);
  const loadReviews = useCallback((signal: AbortSignal) => Promise.all([
    listReviews({ learner_id: learnerId, status: 'pending' }, signal),
    listReviews({ learner_id: learnerId, status: 'completed' }, signal),
  ]), [learnerId, updatedAt, attemptId]);
  const knowledge = useApiResource(loadKnowledge);
  const reviews = useApiResource(loadReviews);
  const state = knowledge.state.status === 'success'
    ? knowledge.state.data.find(item => item.topic_id === topicId && item.learner_id === learnerId) : undefined;
  const reviewItems = reviews.state.status === 'success' ? reviewsForSession(session, reviews.state.data.flat()) : [];
  const pendingReviews = reviewItems.filter(item => item.status === 'pending')
    .sort((a, b) => Date.parse(a.scheduled_for) - Date.parse(b.scheduled_for));
  const dueReview = pendingReviews.find(item => item.is_due === true && !item.question_unavailable);
  const nextReview = dueReview ?? pendingReviews[0];
  const latestReview = reviewItems.filter(item => item.status === 'completed' && item.attempt_id)
    .sort((a, b) => Date.parse(b.submitted_at ?? b.completed_at ?? '') - Date.parse(a.submitted_at ?? a.completed_at ?? ''))[0];
  const timeline = evidenceTimeline(session.id, attempts, reviewItems);
  const data = resource.status === 'success' && resource.data?.diagnosis.id === caseId ? resource.data : null;
  const diagnosis = data?.diagnosis ?? null;
  const execution = diagnosticExecutionDescription(diagnosis, latestStep);
  const rules = diagnosis?.execution_mode === 'rules' && (!latestStep || latestStep.execution_mode === 'rules');
  const modeLabel = rules ? '规则模式' : execution.kind === 'mock' ? '离线模拟模型' : execution.kind === 'live' ? '实时模型' : '来源未知';
  const evidence = groupEvidenceByHypothesis(data?.evidence ?? []);
  const transferUnavailable = activeQuestion?.question_role !== 'transfer_check'
    && (Boolean(transferDispatchNotice) || attemptResult?.next_action === 'transfer_unavailable');
  const unavailableReason = transferUnavailable
    ? learnerDiagnosticText(transferDispatchNotice) ?? '暂无匹配的独立迁移题，迁移证据仍不足。'
    : undefined;
  const transferPassed = attemptResult?.next_action === 'transfer_verified'
    || attemptResult?.next_action === 'matching_headings_transfer_verified' || session.knowledge_state_status === 'transfer_verified';
  const status = state?.status ?? session.knowledge_state_status;

  const refresh = () => {
    onRefresh();
    void knowledge.retry();
    void reviews.retry();
  };

  let action: { title: string; description: string; run: () => void } | undefined;
  if (pendingIntent && diagnosis) action = { title: '恢复上次诊断请求', description: '上次诊断尚未确认，恢复时会沿用同一请求。', run: () => onReplayPending(pendingIntent.action) };
  else if (activeQuestion && session.status !== 'completed' && session.status !== 'paused') {
    const prompts: Record<string, { title: string; description: string }> = {
      initial: { title: '返回作答', description: '完成当前题目后，系统会根据作答决定下一步。' },
      diagnostic_followup: { title: '回答诊断追问', description: '用这道追问区分可能的错误原因。' },
      targeted_practice: { title: '继续针对性训练', description: '已安排一道针对当前错误假设的练习。' },
      transfer_check: { title: '作答独立迁移题', description: '在新的阅读情境里检验能否独立运用。' },
    };
    action = { ...(prompts[activeQuestion.question_role] ?? { title: '前往当前题目', description: '继续本次作答。' }), run: onAnswer };
  } else if (canRetryDiagnosticStep(session, diagnosis)) {
    action = { title: '重试诊断', description: '上次诊断需要重试。', run: onRetryStep };
  } else if (canRunDiagnosticStep(session, diagnosis, attempts)) {
    action = { title: rules ? '继续收集证据' : '请求 Agent 执行下一诊断步骤', description: '让系统根据现有作答安排下一步。', run: onRunStep };
  } else if (session.can_dispatch_transfer && !unavailableReason && !transferPassed && !dueReview) {
    action = { title: '请求独立迁移题', description: '查询是否还有可用的新题。', run: onDispatchTransfer };
  }

  const retentionLabel = reviews.state.status === 'error' ? '复习证据读取失败'
    : reviews.state.status !== 'success' ? '正在读取复习证据'
    : latestReview && isVerifiedRetention(latestReview) ? '本次延迟保持已验证'
    : latestReview?.is_correct === false ? '最近一次复习未通过'
    : latestReview?.is_correct === true ? '复习通过，未取得保持证据'
    : '尚无延迟保持证据';
  const supported = data?.hypotheses.filter(item => item.status === 'supported' || item.status === 'confirmed') ?? [];
  const supportedIds = new Set(supported.map(item => item.id));
  const orderedHypotheses = [...(data?.hypotheses ?? [])].sort(
    (a, b) => Number(supportedIds.has(b.id)) - Number(supportedIds.has(a.id)),
  );
  const diagnosisLoading = Boolean(caseId) && (resource.status === 'idle' || resource.status === 'loading' || (resource.status === 'success' && !data));
  const diagnosisFailed = Boolean(caseId) && resource.status === 'error';
  const conclusion = diagnosisLoading ? '正在读取诊断'
    : diagnosisFailed ? '诊断证据读取失败'
    : supported.length === 1 ? supported[0].name
    : supported.length > 1 ? '多个错误假设获得支持'
    : data ? '现有证据尚无法区分错误原因'
    : '当前会话暂无诊断';
  const uncertainty = diagnosis?.status !== 'resolved' ? learnerDiagnosticText(diagnosis?.uncertainty_note) : undefined;
  const diagnosticDetail = learnerDiagnosticText(latestStep?.decision_reason ?? latestStep?.explanation_text);

  return <DiagnosticInspectorRailFrame className="error-dna" id="error-dna" aria-labelledby="error-dna-title">
    <header className="error-dna-header">
      <div>
        <h2 id="error-dna-title">Error DNA</h2>
        <p>本次诊断与后续练习</p>
      </div>
      <button type="button" className="wb-btn sm" disabled={busy} onClick={refresh}>刷新证据</button>
    </header>

    <div className="error-dna-priority">
      <section className="error-dna-conclusion" aria-labelledby="error-dna-conclusion">
        <div className="error-dna-section-heading">
          <span className="error-dna-label">{supported.length ? '当前诊断假设' : '本次诊断'}</span>
          {diagnosis && <span className="error-dna-chip">{modeLabel}</span>}
        </div>
        <h3 id="error-dna-conclusion" role={diagnosisFailed ? 'alert' : diagnosisLoading ? 'status' : undefined}>{conclusion}</h3>
        {supported.length > 0 && <p>{supported.length === 1 ? '当前证据更支持这个假设，判断可能随新作答调整。' : supported.map(item => item.name).join('、') + '。仍需作答区分原因。'}</p>}
        {!caseId && <p>{timeline.length ? '可在时间线查看已保存的作答。' : '完成作答后，系统会根据证据判断是否需要诊断。'}</p>}
        {diagnosisFailed && <p>可刷新证据后重试。</p>}
        {uncertainty && <p>{uncertainty}</p>}
        {latestStep?.degraded_mode && <p role="status">本次诊断以降级方式继续。{learnerDiagnosticText(latestStep.degradation_reason)}</p>}
        {rules && <small>依据题目规则与作答证据。</small>}
      </section>

      <section className="error-dna-next" aria-labelledby="error-dna-next">
        <h3 id="error-dna-next">下一步</h3>
        {nextReview && <p>{nextReview.retention_eligible ? '保持验证' : '巩固练习'} · {formatDate(nextReview.scheduled_for)} · {nextReview.question_unavailable ? '暂无合格复习题' : nextReview.is_due ? '已到期' : nextReview.is_due === false ? '尚未到期' : '到期状态待确认'}</p>}
        {!nextReview && reviews.state.status === 'success' && timeline.length > 0 && <p>暂无复习安排。</p>}
        {unavailableReason && <p>{unavailableReason}</p>}
        {action && <p>{action.description}</p>}
        {!action && !dueReview && !unavailableReason && <p>{status === 'needs_practice'
          ? '仍需继续练习，当前暂无已分配的训练题。'
          : nextReview?.is_due === false ? '到期后可开始复习。' : '当前暂无可继续的任务。'}</p>}
        {(action || dueReview) && <div className="error-dna-actions">
          {action && <button type="button" className="wb-btn primary" disabled={busy || sessionReadFailed} onClick={action.run}>{action.title}</button>}
          {dueReview && <button type="button" className={`wb-btn${action ? '' : ' primary'}`} disabled={busy} onClick={onReview}>前往复习</button>}
        </div>}
      </section>
    </div>

    <div className="error-dna-overview">
      <div>
        <span className="error-dna-label">主题知识状态</span>
        <strong>{knowledgeStatusLabel(status)}</strong>
        {knowledge.state.status === 'error' && <small role="alert">学习档案读取失败。可刷新证据后重试。</small>}
      </div>
      <div>
        <span className="error-dna-label">本会话延迟保持</span>
        <strong>{retentionLabel}</strong>
        {latestReview && <small>{formatDate(latestReview.submitted_at ?? latestReview.completed_at)}</small>}
      </div>
    </div>

    <div className="error-dna-grid">
      <section aria-labelledby="error-dna-causes">
        <h3 id="error-dna-causes">错误假设</h3>
        {!data?.hypotheses.length && <p>暂无可展开的假设证据。</p>}
        {data && <>
          <div className="error-dna-cards">
            {orderedHypotheses.map(hypothesis => {
              const items = evidence.get(hypothesis.id) ?? [];
              return <article className="error-dna-cause" key={hypothesis.id}>
                <div className="error-dna-section-heading">
                  <h4>{hypothesis.name}</h4>
                  <span className="error-dna-chip" data-relation={hypothesis.status === 'supported' ? 'supports' : hypothesis.status === 'lowered' ? 'contradicts' : undefined}>{hypothesisStatusLabel(hypothesis.status)}</span>
                </div>
                <details className="error-dna-disclosure">
                  <summary>证据详情 <small>支持 {items.filter(item => item.relation === 'supports').length} · 削弱 {items.filter(item => item.relation === 'contradicts').length} · 中性 {items.filter(item => item.relation === 'neutral').length}</small></summary>
                  {learnerDiagnosticText(hypothesis.description) && <p>{learnerDiagnosticText(hypothesis.description)}</p>}
                  {learnerDiagnosticText(hypothesis.missing_evidence_desc) && <p><strong>仍需核实：</strong>{learnerDiagnosticText(hypothesis.missing_evidence_desc)}</p>}
                  {items.length ? <ul className="error-dna-evidence">
                    {items.map(item => <li key={item.id}>
                      <span className="error-dna-chip" data-relation={item.relation}>{item.relation === 'contradicts' ? '削弱' : evidenceRelationLabel(item.relation)}</span>
                      <div>{learnerDiagnosticText(item.summary) ?? '原始证据见诊断记录。'}<small>{evidenceSourceLabel(item.source_type)}{learnerDiagnosticText(item.reliability_note) && ` · ${learnerDiagnosticText(item.reliability_note)}`}</small>{item.evidence_validity_status && item.evidence_validity_status !== 'eligible' && <small className="error-dna-evidence-warning">此证据当前{evidenceValidityLabel(item.evidence_validity_status)}：{learnerEvidenceValidityReason(item.evidence_validity_status, item.evidence_validity_reason)}</small>}</div>
                    </li>)}
                  </ul> : <p>尚无与此假设关联的证据。</p>}
                </details>
              </article>;
            })}
          </div>
        </>}
      </section>

      <section aria-labelledby="error-dna-timeline">
        <h3 id="error-dna-timeline">学习证据时间线</h3>
        {reviews.state.status === 'error' && <p role="alert" className="error-dna-error">复习记录读取失败。当前仅展示会话作答。</p>}
        {!timeline.length && <p>尚无已保存的作答。</p>}
        {!!timeline.length && <ol className="error-dna-timeline">
          {timeline.map(event => <li key={event.id}>
            <div className="error-dna-section-heading"><h4>{event.title}</h4><span>{event.result}</span></div>
            <small>{formatDate(event.time)}</small>
            {event.questionId && <details className="error-dna-disclosure"><summary>查看作答记录</summary>{event.summary && <p>{learnerDiagnosticText(event.summary) ?? event.summary}</p>}{event.answer && <blockquote>{event.answer}</blockquote>}<small>题目 {event.questionId} · 作答 {event.id}</small></details>}
          </li>)}
        </ol>}
      </section>
    </div>

    {data && <details className="error-dna-disclosure error-dna-audit">
      <summary>诊断记录与来源</summary>
      {diagnosticDetail && <p>{diagnosticDetail}</p>}
      <p>{diagnosticStatusLabel(data.diagnosis.status)} · 案例 <code>{data.diagnosis.id}</code> · 原始作答 <code>{data.triggerAttempt.id}</code></p>
      <p>执行方式 <code>{data.diagnosis.execution_mode}</code> · 不确定性 <code>{data.diagnosis.uncertainty_level}</code></p>
      <ul>{data.evidence.map(item => <li key={item.id}>
        <code>{item.source_ref}</code> · {item.summary}{item.reliability_note && ` · ${item.reliability_note}`}
        {item.observation && <p>
          题项 <code>{item.observation.item_id}</code> · 段落 <code>{item.observation.paragraph_id}</code> · 所选标题 <code>{item.observation.selected_heading_id}</code>
          <br />作答 <code>{item.observation.attempt_id}</code> · 题目 <code>{item.observation.question_id}</code>
          <br />题组版本 <code>{item.observation.group_version_id}</code> · 评分规则 <code>{item.observation.rule_version_id}</code>（版本 {item.observation.evaluation_rule_version}）
        </p>}
      </li>)}</ul>
    </details>}
  </DiagnosticInspectorRailFrame>;
}
