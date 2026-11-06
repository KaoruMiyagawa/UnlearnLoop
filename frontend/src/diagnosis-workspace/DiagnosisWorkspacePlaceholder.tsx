import React from 'react';
import { StatusBadge } from '../design-system/StatusBadge';

export const DiagnosisWorkspacePlaceholder: React.FC = () => {
  return (
    <section className="rounded-control border border-border-default bg-surface-raised p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-default pb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-action-primary">
            diagnosis-workspace
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-text-primary">
            错误诊断中心（Stage 1 骨架就绪）
          </h1>
        </div>
        <StatusBadge tone="warning" label="需要证据 · Stage 3/5 决策接入" />
      </div>

      <p className="mt-4 max-w-reading text-sm text-text-secondary">
        本工作空间将在后续阶段呈现并列候选错误原因、置信度、支持/缺失证据、区分性追问及可回溯决策时间线。当前阶段仅完成工作空间路由与布局容器初始化。
      </p>
    </section>
  );
};
