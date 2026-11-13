import React, { useCallback } from 'react';
import { listReviews } from '../api/reviews';
import type { ReviewItem } from '../api/types';
import { useApiResource } from '../learning-workspace/useApiResource';
import type { WorkspaceId } from '../app-shell/navigation';

const LEARNER_ID = 'default_learner';

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '计划时间暂不可用' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export const ReviewHomeEntry: React.FC<{
  onNavigateWorkspace: (workspace: WorkspaceId) => void;
}> = ({ onNavigateWorkspace }) => {
  const loader = useCallback((signal: AbortSignal) => listReviews({ learner_id: LEARNER_ID, status: 'pending' }, signal), []);
  const resource = useApiResource<ReviewItem[]>(loader);
  if (resource.state.status === 'loading') return <section className="focus-home-review" role="status">正在读取复习计划…</section>;
  if (resource.state.status === 'error') return <section className="focus-home-review" role="alert"><div><strong>暂时无法读取复习计划</strong><p>真实模式不会用演示记录替代。</p></div><button className="focus-button-quiet" onClick={() => void resource.retry()}>重试</button></section>;
  if (resource.state.status !== 'success') return <section className="focus-home-review" role="status">正在读取复习计划…</section>;
  const reviews = resource.state.data;
  const dueCount = reviews.filter((item) => item.is_due === true).length;
  const next = reviews[0];
  return <section className="focus-home-review" aria-label="复习计划">
    <div className="focus-home-review-copy"><div className="focus-eyebrow">复习安排 · 服务端记录</div><strong>{dueCount > 0 ? `${dueCount} 项已到期` : reviews.length > 0 ? `${reviews.length} 项待复习` : '暂无待复习任务'}</strong>
      {next ? <p>{next.topic_title} · {next.is_due ? '现在可以开始' : `计划时间 ${formatDate(next.scheduled_for)}`}</p> : <p>新的复习会在获得有效学习证据后安排。</p>}
    </div>
    <button type="button" className={dueCount ? 'focus-button' : 'focus-button-secondary'} onClick={() => onNavigateWorkspace('review')}>打开复习中心</button>
  </section>;
};
