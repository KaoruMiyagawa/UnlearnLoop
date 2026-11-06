import React from 'react';
import { StatusBadge } from '../design-system/StatusBadge';

export const ProfileWorkspacePlaceholder: React.FC = () => {
  return (
    <section className="rounded-control border border-border-default bg-surface-raised p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-default pb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-action-primary">
            profile-workspace
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-text-primary">
            学习档案与数据控制（Stage 1 骨架就绪）
          </h1>
        </div>
        <StatusBadge tone="neutral" label="证据不足 · Stage 6 接入" />
      </div>

      <p className="mt-4 max-w-reading text-sm text-text-secondary">
        本工作空间将在 Stage 6 展示各知识点的可解释掌握状态（稳定、需要练习、需要诊断、证据不足）、远程模型调用隐私开关及本地学习数据清理入口。
      </p>
    </section>
  );
};
