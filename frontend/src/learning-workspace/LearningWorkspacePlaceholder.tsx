import React from 'react';
import { StatusBadge } from '../design-system/StatusBadge';

export const LearningWorkspacePlaceholder: React.FC = () => {
  return (
    <section className="rounded-control border border-border-default bg-surface-raised p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-default pb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-action-primary">
            learning-workspace
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-text-primary">
            学习工作区（Stage 1 骨架就绪）
          </h1>
        </div>
        <StatusBadge tone="neutral" label="待处理 · Stage 4/5 业务接入" />
      </div>

      <p className="mt-4 max-w-reading text-sm text-text-secondary">
        本工作空间将在后续阶段承载跨学科学习材料阅读、题目呈现、答案草稿保留与作答提交。根据 Stage 1 工程边界约束，当前阶段不提前实现业务表单与题目生成逻辑。
      </p>
    </section>
  );
};
