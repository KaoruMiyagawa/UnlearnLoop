import React from 'react';
import { HealthResponse } from '../api/health';
import { getApiBaseUrl } from '../api/client';
import { StatusBadge } from './StatusBadge';

export type HealthConnectionState =
  | { kind: 'loading' }
  | { kind: 'connected'; data: HealthResponse }
  | { kind: 'error'; message: string; code?: string; requestId?: string };

interface HealthStatusCardProps {
  state: HealthConnectionState;
  onRefresh: () => void;
}

export const HealthStatusCard: React.FC<HealthStatusCardProps> = ({
  state,
  onRefresh,
}) => {
  const isChecking = state.kind === 'loading';

  return (
    <section
      aria-labelledby="health-card-heading"
      className="rounded-control border border-border-default bg-surface-raised p-6 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border-default pb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-action-primary">
            系统连接基线 · /api/v1/health
          </p>
          <h2
            id="health-card-heading"
            className="mt-1 text-xl font-semibold text-text-primary"
          >
            前后端健康检查与子系统就绪状态
          </h2>
          <p className="mt-1 text-sm text-text-secondary">
            目标后端地址：<code className="font-mono">{getApiBaseUrl()}/api/v1/health</code>
          </p>
        </div>

        <div className="flex items-center gap-3">
          {state.kind === 'loading' && (
            <StatusBadge tone="primary" label="正在检查连接…" />
          )}
          {state.kind === 'connected' && (
            <StatusBadge tone="success" label="后端已连接 (OK)" />
          )}
          {state.kind === 'error' && (
            <StatusBadge tone="error" label="连接失败" />
          )}

          <button
            type="button"
            onClick={onRefresh}
            disabled={isChecking}
            className="h-10 min-w-[116px] rounded-control border border-border-default bg-surface-raised px-4 text-sm font-semibold text-text-primary transition hover:bg-surface-subtle focus:outline-none focus:ring-2 focus:ring-action-primary disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isChecking ? '检查中…' : '重新检查健康'}
          </button>
        </div>
      </div>

      <div className="mt-4">
        {state.kind === 'loading' && (
          <div
            role="status"
            className="rounded-control border border-border-default bg-surface-subtle p-4 text-sm text-text-secondary"
          >
            正在请求后端健康检查端点 <code className="font-mono">/api/v1/health</code>，请稍候…
          </div>
        )}

        {state.kind === 'error' && (
          <div
            role="alert"
            className="rounded-control border border-red-200 bg-red-50 p-4 text-sm text-feedback-error"
          >
            <p className="font-semibold">后端健康检查未通过</p>
            <p className="mt-1">{state.message}</p>
            <div className="mt-2 flex flex-wrap gap-4 text-xs text-text-secondary">
              {state.code && (
                <span>
                  错误码：<code className="font-mono">{state.code}</code>
                </span>
              )}
              {state.requestId && (
                <span>
                  关联 ID：<code className="font-mono">{state.requestId}</code>
                </span>
              )}
            </div>
            <p className="mt-2 text-xs text-text-secondary">
              影响范围：当前无法读取或提交后端数据。请确认后端服务已通过 Uvicorn 启动并监听对应端口，然后点击右上角“重新检查健康”。
            </p>
          </div>
        )}

        {state.kind === 'connected' && (
          <div className="space-y-4">
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-control border border-border-default bg-surface-page p-3">
                <dt className="text-xs text-text-secondary">服务与版本</dt>
                <dd className="mt-1 text-sm font-semibold text-text-primary">
                  {state.data.service} · v{state.data.version}
                </dd>
              </div>
              <div className="rounded-control border border-border-default bg-surface-page p-3">
                <dt className="text-xs text-text-secondary">运行环境 / 阶段</dt>
                <dd className="mt-1 text-sm font-semibold text-text-primary">
                  {state.data.environment} ({state.data.stage})
                </dd>
              </div>
              <div className="rounded-control border border-border-default bg-surface-page p-3">
                <dt className="text-xs text-text-secondary">持久化配置边界</dt>
                <dd className="mt-1 text-sm font-semibold text-text-primary">
                  SQLAlchemy：{state.data.subsystems.persistence === 'configured' ? '已配置' : '未配置'}
                </dd>
              </div>
              <div className="rounded-control border border-border-default bg-surface-page p-3">
                <dt className="text-xs text-text-secondary">模型服务边界 (Stage 3 预留)</dt>
                <dd className="mt-1 text-sm font-semibold text-text-primary">
                  {state.data.subsystems.model_provider} ·{' '}
                  {state.data.subsystems.remote_model_enabled
                    ? '远程调用已启用'
                    : '远程调用默认关闭'}
                </dd>
              </div>
            </dl>

            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-secondary">
              <span>
                请求关联 ID (<code className="font-mono">request_id</code>)：
                <code className="ml-1 font-mono text-text-primary">
                  {state.data.request_id}
                </code>
              </span>
              <span>
                服务端时间 (<code className="font-mono">ISO 8601</code>)：
                <code className="ml-1 font-mono text-text-primary">
                  {state.data.timestamp}
                </code>
              </span>
            </div>
          </div>
        )}
      </div>
    </section>
  );
};
