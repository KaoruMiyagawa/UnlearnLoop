import React from 'react';
import { StatusBadge } from '../design-system/StatusBadge';

export const ReviewWorkspacePlaceholder: React.FC = () => {
  return (
    <section className="rounded-control border border-border-default bg-surface-raised p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-default pb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-action-primary">
            review-workspace
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-text-primary">
            复习历史与迁移验证（Stage 1 骨架就绪）
          </h1>
        </div>
        <StatusBadge tone="neutral" label="待处理 · Stage 6 接入" />
      </div>

      <p className="mt-4 max-w-reading text-sm text-text-secondary">
        本工作空间将在 Stage 6 承载按错误模式与遗忘风险组织的复习队列、历史诊断证据回看以及变式迁移验证。
      </p>
    </section>
  );
};
