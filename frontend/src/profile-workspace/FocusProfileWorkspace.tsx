import React, { useCallback, useMemo } from 'react';
import { listKnowledgeStates, listLearningHistory } from '../api/profile';
import { listReviews } from '../api/reviews';
import type { KnowledgeState, LearningHistoryEvent, ReviewItem } from '../api/types';
import { useApiResource } from '../learning-workspace/useApiResource';
import type { WorkspaceId } from '../app-shell/navigation';

const LEARNER_ID = 'default_learner';

function formatDate(value?: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return '暂无记录';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function learningStatus(value: KnowledgeState['status']): string {
  switch (value) {
    case 'stable': return '当前迁移验证通过';
    case 'transfer_verified': return '独立迁移验证通过';
    case 'needs_practice': return '需要继续学习';
    case 'needs_diagnosis': return '需要进一步诊断';
    case 'insufficient_evidence': return '证据还不充分';
  }
}

function retentionStatus(value?: KnowledgeState['retention_status']): string {
  switch (value) {
    case 'review_due': return '已安排延迟复习';
    case 'delayed_check_passed': return '已获得延迟保持证据';
    case 'review_failed': return '最近复习需要继续学习';
    default: return '尚未获得延迟保持证据';
  }
}

function HistoryNotice({ state, retry }: { state: { status: string; error?: unknown }; retry: () => void }) {
  if (state.status === 'loading') return <div role="status" className="focus-notice neutral">正在读取服务端学习记录…</div>;
  if (state.status === 'error') return <div role="alert" className="focus-notice danger">学习档案读取失败。真实模式不会用演示数据替代。<button className="focus-button-quiet" onClick={retry}>重试读取</button></div>;
  return null;
}

export const FocusProfileWorkspace: React.FC<{
  onNavigateWorkspace: (workspace: WorkspaceId) => void;
}> = ({ onNavigateWorkspace }) => {
  const loadStates = useCallback((signal: AbortSignal) => listKnowledgeStates(LEARNER_ID, signal), []);
  const loadHistory = useCallback((signal: AbortSignal) => listLearningHistory(LEARNER_ID, 100, signal), []);
  const loadPending = useCallback((signal: AbortSignal) => listReviews({ learner_id: LEARNER_ID, status: 'pending' }, signal), []);
  const states = useApiResource<KnowledgeState[]>(loadStates);
  const history = useApiResource<LearningHistoryEvent[]>(loadHistory);
  const reviews = useApiResource<ReviewItem[]>(loadPending);

  const transferByTopic = useMemo(() => {
    const map = new Map<string, LearningHistoryEvent>();
    if (history.state.status === 'success') {
      for (const event of history.state.data) {
        if (event.kind === 'transfer_check' && !map.has(event.topic_id)) map.set(event.topic_id, event);
      }
    }
    return map;
  }, [history.state]);
  const nextReviewByTopic = useMemo(() => {
    const map = new Map<string, ReviewItem>();
    if (reviews.state.status === 'success') {
      for (const item of reviews.state.data) if (!map.has(item.topic_id)) map.set(item.topic_id, item);
    }
    return map;
  }, [reviews.state]);

  const allEvents = history.state.status === 'success' ? history.state.data : [];
  return <div className="focus-page focus-profile-page">
    <div className="focus-page-content">
      <header className="focus-page-header">
        <div className="focus-eyebrow">YOUR LEARNING RECORD · REAL API</div>
        <h1 className="focus-page-title">看见哪些理解经过了验证，也看见还缺什么证据。</h1>
        <p className="focus-page-subtitle">当前迁移通过与长期保持是不同证据。一次延迟复习通过，也不能证明永久掌握。</p>
      </header>

      <section className="focus-page-section" aria-labelledby="knowledge-record-title">
        <div className="focus-review-section-heading"><div><h2 id="knowledge-record-title">知识点进展</h2><p>状态、保持记录和复习安排来自服务端。</p></div></div>
        <HistoryNotice state={states.state} retry={() => void states.retry()} />
        <HistoryNotice state={reviews.state} retry={() => void reviews.retry()} />
        {states.state.status === 'success' && states.state.data.length === 0 && <div className="focus-empty">还没有知识点进展记录。完成一次学习与独立迁移后，这里会显示真实证据。</div>}
        {states.state.status === 'success' && states.state.data.length > 0 && <div className="focus-profile-list">
          {states.state.data.map((item) => {
            const transfer = transferByTopic.get(item.topic_id);
            const nextReview = nextReviewByTopic.get(item.topic_id);
            return <article className="focus-profile-topic" key={item.id}>
              <div className="focus-profile-topic-heading"><div><h3>{item.topic_title}</h3><p>{learningStatus(item.status)}</p></div><span className={`focus-state-tag ${item.retention_status === 'delayed_check_passed' ? 'verified' : ''}`}>{retentionStatus(item.retention_status)}</span></div>
              <dl className="focus-profile-facts">
                <div><dt>最近迁移验证</dt><dd>{transfer ? `${formatDate(transfer.occurred_at)} · ${transfer.summary}` : item.last_transfer_attempt_id ? `已记录作答 ${item.last_transfer_attempt_id}` : '暂无独立迁移记录'}</dd></div>
                <div><dt>延迟复习通过</dt><dd>{item.retention_evidence_count ?? 0} 次 · 最近有效证据 {formatDate(item.last_retention_verified_at)}</dd></div>
                <div><dt>下次复习</dt><dd>{nextReview ? `${formatDate(nextReview.scheduled_for)} · ${nextReview.is_due ? '已到期' : '尚未到期'}` : '当前没有待办计划'}</dd></div>
                <div><dt>长期保持</dt><dd>尚未证明长期保持；复习记录仅代表已获得的延迟证据。</dd></div>
              </dl>
              {item.unresolved_error_reasons && item.unresolved_error_reasons.length > 0
                ? <details className="focus-disclosure"><summary>仍待验证的可能原因（{item.unresolved_error_reasons.length}）</summary><div className="focus-disclosure-content">{item.unresolved_error_reasons.map((reason, index) => <div className="focus-reason" key={`${reason.title}-${index}`}><strong>{reason.title}</strong><p>{reason.summary}</p><small>当前判断：{reason.status} · 仍需结合新证据确认</small></div>)}</div></details>
                : <p className="focus-help">当前没有由服务端标记为待验证的错误原因。</p>}
            </article>;
          })}
        </div>}
      </section>

      <section className="focus-page-section" aria-labelledby="history-title">
        <div className="focus-review-section-heading"><div><h2 id="history-title">学习历史</h2><p>按时间记录作答、诊断、迁移验证和复习。原始答案和内部评分规则不会显示。</p></div></div>
        <HistoryNotice state={history.state} retry={() => void history.retry()} />
        {history.state.status === 'success' && allEvents.length === 0 && <div className="focus-empty">还没有可展示的学习历史。</div>}
        {history.state.status === 'success' && allEvents.length > 0 && <ol className="focus-timeline">
          {allEvents.map((event) => <li className="focus-timeline-item" key={event.id}>
            <span className="focus-timeline-dot" aria-hidden="true" />
            <div className="focus-timeline-main"><div className="focus-timeline-heading"><strong>{event.title}</strong><time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time></div><div className="focus-timeline-topic">{event.topic_title}</div><p>{event.summary}</p><details className="focus-disclosure"><summary>查看证据摘要</summary><div className="focus-disclosure-content">{event.evidence_summary}</div></details></div>
          </li>)}
        </ol>}
      </section>
      <div className="focus-actions"><button className="focus-button" onClick={() => onNavigateWorkspace('review')}>前往复习中心</button><button className="focus-button-quiet" onClick={() => onNavigateWorkspace('home')}>返回首页</button></div>
    </div>
  </div>;
};
