import React, { useCallback, useEffect, useState } from 'react';
import { ApiClientError } from './api/client';
import { fetchBackendHealth } from './api/health';
import { AppShell } from './app-shell/AppShell';
import {
  resolveWorkspaceFromPath,
  WORKSPACE_NAV_ITEMS,
  WorkspaceId,
} from './app-shell/navigation';
import {
  HealthConnectionState,
  HealthStatusCard,
} from './design-system/HealthStatusCard';
import { DiagnosisWorkspacePlaceholder } from './diagnosis-workspace/DiagnosisWorkspacePlaceholder';
import { LearningWorkspacePlaceholder } from './learning-workspace/LearningWorkspacePlaceholder';
import { ProfileWorkspacePlaceholder } from './profile-workspace/ProfileWorkspacePlaceholder';
import { ReviewWorkspacePlaceholder } from './review-workspace/ReviewWorkspacePlaceholder';

export const App: React.FC = () => {
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceId>(() =>
    resolveWorkspaceFromPath(window.location.pathname),
  );
  const [healthState, setHealthState] = useState<HealthConnectionState>({
    kind: 'loading',
  });

  const checkHealth = useCallback(async () => {
    setHealthState({ kind: 'loading' });
    try {
      const response = await fetchBackendHealth();
      setHealthState({ kind: 'connected', data: response });
    } catch (err) {
      if (err instanceof ApiClientError) {
        setHealthState({
          kind: 'error',
          message: err.message,
          code: err.code,
          requestId: err.requestId,
        });
      } else {
        setHealthState({
          kind: 'error',
          message: '检查后端连接时发生未知错误。',
        });
      }
    }
  }, []);

  useEffect(() => {
    void checkHealth();
  }, [checkHealth]);

  useEffect(() => {
    const handlePopState = () => {
      setActiveWorkspace(resolveWorkspaceFromPath(window.location.pathname));
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigateWorkspace = (workspace: WorkspaceId) => {
    const navItem = WORKSPACE_NAV_ITEMS.find((item) => item.id === workspace);
    if (navItem && window.location.pathname !== navItem.path) {
      window.history.pushState({}, '', navItem.path);
    }
    setActiveWorkspace(workspace);
  };

  const backendConnected =
    healthState.kind === 'loading'
      ? null
      : healthState.kind === 'connected';

  return (
    <AppShell
      activeWorkspace={activeWorkspace}
      onSelectWorkspace={navigateWorkspace}
      backendConnected={backendConnected}
    >
      {activeWorkspace === 'home' && (
        <section className="rounded-control border border-border-default bg-surface-raised p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wider text-action-primary">
            UnlearnLoop · Stage 1 工程基线
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-text-primary sm:text-3xl">
            从错误中学习，用证据验证真正掌握
          </h1>
          <p className="mt-2 max-w-reading text-base text-text-secondary">
            系统不把一次答错直接等同于单一结论，而是保留多个候选错误原因、收集区分性证据，并在新情境中验证知识迁移。
          </p>

          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-control border border-border-default bg-surface-page p-4">
              <span className="text-xs font-semibold text-action-primary">
                步骤 01
              </span>
              <h2 className="mt-1 text-base font-semibold text-text-primary">
                选择知识点与问题
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                阅读简短材料并提交作答，原始作答将作为第一条诊断证据保存。
              </p>
            </div>
            <div className="rounded-control border border-border-default bg-surface-page p-4">
              <span className="text-xs font-semibold text-action-primary">
                步骤 02
              </span>
              <h2 className="mt-1 text-base font-semibold text-text-primary">
                区分性追问与诊断
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                并列保留候选错误假设，通过低成本追问排除或确认卡点。
              </p>
            </div>
            <div className="rounded-control border border-border-default bg-surface-page p-4">
              <span className="text-xs font-semibold text-action-primary">
                步骤 03
              </span>
              <h2 className="mt-1 text-base font-semibold text-text-primary">
                针对性干预与迁移验证
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                完成变式迁移验证后更新知识状态，区分“碰巧答对”与“真正掌握”。
              </p>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => navigateWorkspace('learning')}
              className="h-11 rounded-control bg-action-primary px-5 text-sm font-semibold text-white transition hover:bg-action-primary-hover focus:outline-none focus:ring-2 focus:ring-action-primary"
            >
              进入学习工作区
            </button>
            <button
              type="button"
              onClick={() => navigateWorkspace('diagnosis')}
              className="h-11 rounded-control border border-border-default bg-surface-raised px-5 text-sm font-semibold text-text-primary transition hover:bg-surface-subtle focus:outline-none focus:ring-2 focus:ring-action-primary"
            >
              查看诊断中心结构
            </button>
          </div>
        </section>
      )}

      {activeWorkspace === 'learning' && <LearningWorkspacePlaceholder />}
      {activeWorkspace === 'diagnosis' && <DiagnosisWorkspacePlaceholder />}
      {activeWorkspace === 'review' && <ReviewWorkspacePlaceholder />}
      {activeWorkspace === 'profile' && <ProfileWorkspacePlaceholder />}

      {/* Always visible live backend health status card */}
      <HealthStatusCard state={healthState} onRefresh={() => void checkHealth()} />
    </AppShell>
  );
};
