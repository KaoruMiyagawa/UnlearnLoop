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
import { DiagnosticInspectorRail } from './design-system/DiagnosticInspectorRail';
import {
  DecisionTimelineItemView,
  INITIAL_DECISION_TIMELINE,
  INITIAL_LOOP_STAGE_SNAPSHOTS,
  LoopStageId,
  UiSimulationMode,
} from './design-system/stage5WorkbenchModel';
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

  // Domain State Machine Progression (Steps 1..6) — Cannot skip ahead arbitrarily via UI!
  const [currentStage, setCurrentStage] = useState<LoopStageId>(2);
  const [maxUnlockedStage, setMaxUnlockedStage] = useState<LoopStageId>(2);
  const [stageGuardAlert, setStageGuardAlert] = useState<string | null>(null);
  const [uiMode, setUiMode] = useState<UiSimulationMode>('normal');

  // Local Answer Draft Cache per Loop Stage (preserves draft across navigation & error states)
  const [draftsByStage, setDraftsByStage] = useState<Record<LoopStageId, string>>(() => ({
    1: INITIAL_LOOP_STAGE_SNAPSHOTS[1].task.defaultDraft,
    2: INITIAL_LOOP_STAGE_SNAPSHOTS[2].task.defaultDraft,
    3: INITIAL_LOOP_STAGE_SNAPSHOTS[3].task.defaultDraft,
    4: INITIAL_LOOP_STAGE_SNAPSHOTS[4].task.defaultDraft,
    5: INITIAL_LOOP_STAGE_SNAPSHOTS[5].task.defaultDraft,
    6: INITIAL_LOOP_STAGE_SNAPSHOTS[6].task.defaultDraft,
  }));

  const [timeline] = useState<DecisionTimelineItemView[]>(INITIAL_DECISION_TIMELINE);

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

  // Enforces strict domain state machine: cannot jump to an unreached stage without completing prior actions
  const handleSelectStage = (targetStage: LoopStageId) => {
    if (targetStage > maxUnlockedStage) {
      const requiredSnapshot = INITIAL_LOOP_STAGE_SNAPSHOTS[maxUnlockedStage];
      setStageGuardAlert(
        `第 ${targetStage} 步（${INITIAL_LOOP_STAGE_SNAPSHOTS[targetStage].shortLabel}）尚未解锁！当前会话处于第 ${maxUnlockedStage} 步（${requiredSnapshot.sessionStatusDisplay}），请先在工作台完成当前受控步骤后再推进，禁止跳过领域状态机。`,
      );
      return;
    }

    setStageGuardAlert(null);
    setCurrentStage(targetStage);
    if (activeWorkspace === 'home' || activeWorkspace === 'profile') {
      navigateWorkspace('learning');
    }
  };

  const handleAdvanceFromCurrentStage = () => {
    setStageGuardAlert(null);
    if (currentStage < 6) {
      const nextStage = (currentStage + 1) as LoopStageId;
      setCurrentStage(nextStage);
      if (nextStage > maxUnlockedStage) {
        setMaxUnlockedStage(nextStage);
      }
    }
  };

  const handleStepBack = () => {
    setStageGuardAlert(null);
    if (currentStage > 1) {
      setCurrentStage((currentStage - 1) as LoopStageId);
    }
  };

  const handleSyncStageFromTransfer = (targetStage: LoopStageId) => {
    setStageGuardAlert(null);
    setCurrentStage(targetStage);
    if (targetStage > maxUnlockedStage) {
      setMaxUnlockedStage(targetStage);
    }
  };

  const handleResetToStageOne = () => {
    setStageGuardAlert(null);
    setUiMode('normal');
    setCurrentStage(1);
    setMaxUnlockedStage(1);
  };

  const backendConnected =
    healthState.kind === 'loading'
      ? null
      : healthState.kind === 'connected';

  const currentSnapshot = INITIAL_LOOP_STAGE_SNAPSHOTS[currentStage];
  const isMastered = maxUnlockedStage >= 6 || currentStage === 6;

  return (
    <AppShell
      activeWorkspace={activeWorkspace}
      onSelectWorkspace={navigateWorkspace}
      backendConnected={backendConnected}
      currentStage={currentStage}
      maxUnlockedStage={maxUnlockedStage}
      onSelectStage={handleSelectStage}
      stageGuardAlert={stageGuardAlert}
      onDismissGuardAlert={() => setStageGuardAlert(null)}
      uiMode={uiMode}
      onChangeUiMode={setUiMode}
      onResetProgression={handleResetToStageOne}
    >
      {/* 1. Learning Home (学习焦点总览) */}
      {activeWorkspace === 'home' && (
        <div>
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--action-primary)' }}>
              UNLEARNLOOP · SCHEME B PRECISION WORKBENCH
            </div>
            <h1 style={{ margin: '2px 0 6px', fontSize: 24, fontWeight: 700 }}>
              今日学习焦点与证据待办总览
            </h1>
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: 14 }}>
              以清晰的任务卡片、受控六步闭环进度条与双栏实时证据检视器组织完整诊断驱动学习体验。
            </p>
          </div>

          {/* 4 KPI Summary Cards */}
          <div className="wb-kpi-row">
            <div className="wb-kpi-box">
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>待区分竞争性错误假设</div>
              <div className="wb-kpi-val" style={{ color: 'var(--warning)' }}>
                {currentSnapshot.hypotheses.length} 个
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                位于 <code>py-for-loop</code> 活跃会话
              </div>
            </div>

            <div className="wb-kpi-box">
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>待独立变式迁移验证</div>
              <div className="wb-kpi-val" style={{ color: 'var(--action-primary)' }}>
                {isMastered ? '0 项 (已通过)' : '1 项'}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                强制要求未接触过的新情境题
              </div>
            </div>

            <div className="wb-kpi-box">
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>待执行间隔复习 (ReviewItem)</div>
              <div className="wb-kpi-val" style={{ color: 'var(--danger)' }}>
                2 项
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                因迁移验证首次失败与会话挂起触发
              </div>
            </div>

            <div className="wb-kpi-box">
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>已验证操作性掌握 (stable)</div>
              <div className="wb-kpi-val" style={{ color: 'var(--success)' }}>
                {isMastered ? '3 / 5' : '2 / 5'}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                全部具备独立新题迁移证据链
              </div>
            </div>
          </div>

          <div className="wb-grid">
            <div>
              {/* Primary Active Diagnostic Task Card */}
              <section className="wb-card" aria-labelledby="home-primary-task-title">
                <div className="wb-card-head">
                  <h2 id="home-primary-task-title" className="wb-card-title">
                    当前主任务：完成 <code>py-for-loop</code> 诊断追问与变式迁移验证
                  </h2>
                  <span className="wb-badge amber">
                    会话状态：{currentSnapshot.sessionStatusDisplay}
                  </span>
                </div>
                <div className="wb-card-body">
                  <p style={{ marginTop: 0, color: 'var(--text-secondary)' }}>
                    上次初始作答提交了 <code>"3"</code>（仅包含最终数字，缺少逐轮变量追踪）。系统已保存不可变原始作答快照{' '}
                    <code>#att_01_init</code>，并生成并列候选错误假设{' '}
                    <code>H1: range_start_at_one</code> 与{' '}
                    <code>H2: loop_memorized_without_trace</code>。
                  </p>
                  <div
                    style={{
                      padding: '12px 14px',
                      borderRadius: 8,
                      background: 'var(--surface-page)',
                      border: '1px solid var(--border-default)',
                      fontSize: 13,
                      marginBottom: 14,
                    }}
                  >
                    <strong>当前闭环进度（第 {currentStage} / 6 步）：</strong>{' '}
                    {currentSnapshot.stageTitle}
                  </div>
                  <div className="wb-btn-group">
                    <button
                      type="button"
                      className="wb-btn primary"
                      onClick={() => navigateWorkspace('learning')}
                    >
                      进入双栏学习工作台继续闭环 →
                    </button>
                    <button
                      type="button"
                      className="wb-btn"
                      onClick={() => navigateWorkspace('diagnosis')}
                    >
                      查看 Agent 诊断检视器
                    </button>
                    <button
                      type="button"
                      className="wb-btn"
                      onClick={() => navigateWorkspace('transfer')}
                    >
                      进入变式迁移验证室 (防刷分演练)
                    </button>
                  </div>
                </div>
              </section>

              {/* Secondary Due Review & Pending Clues Card */}
              <section className="wb-card" aria-labelledby="home-secondary-queue-title">
                <div className="wb-card-head">
                  <h2 id="home-secondary-queue-title" className="wb-card-title">
                    待处理复习与未结案会话队列
                  </h2>
                  <span className="wb-badge slate">按遗忘风险与未决假设排序</span>
                </div>
                <div className="wb-card-body" style={{ display: 'grid', gap: 10 }}>
                  <div
                    style={{
                      padding: '11px 14px',
                      borderRadius: 8,
                      border: '1px solid var(--border-default)',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 10,
                      flexWrap: 'wrap',
                    }}
                  >
                    <div>
                      <strong>
                        <code>py-list-reference</code> · 列表引用与浅拷贝别名
                      </strong>
                      <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                        会话已结束 (<code>completed</code>) 但未掌握 (<code>needs_practice</code>) · 今日到期复习
                      </div>
                    </div>
                    <button
                      type="button"
                      className="wb-btn sm"
                      onClick={() => navigateWorkspace('profile')}
                    >
                      前往复习队列处理 →
                    </button>
                  </div>

                  <div
                    style={{
                      padding: '11px 14px',
                      borderRadius: 8,
                      border: '1px solid var(--border-default)',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 10,
                      flexWrap: 'wrap',
                    }}
                  >
                    <div>
                      <strong>
                        <code>py-if-elif-else</code> · 条件分支互斥与短路求值
                      </strong>
                      <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                        会话已暂停 (<code>paused</code>) · 2 个候选错误假设等待区分性证据
                      </div>
                    </div>
                    <button
                      type="button"
                      className="wb-btn sm"
                      onClick={() => navigateWorkspace('profile')}
                    >
                      查看知识状态矩阵 →
                    </button>
                  </div>
                </div>
              </section>

              {/* Live Backend Health Status Card */}
              <HealthStatusCard state={healthState} onRefresh={() => void checkHealth()} />
            </div>

            {/* Right Live Agent Diagnostic & Evidence Inspector Rail */}
            <DiagnosticInspectorRail
              snapshot={currentSnapshot}
              currentStage={currentStage}
              maxUnlockedStage={maxUnlockedStage}
              uiMode={uiMode}
              timeline={timeline}
              onRetryFromError={() => setUiMode('normal')}
              onRestoreNormalMode={() => setUiMode('normal')}
              onOpenFullDiagnosis={() => navigateWorkspace('diagnosis')}
              compactMode={true}
            />
          </div>
        </div>
      )}

      {/* 2. Learning Workspace (双栏学习工作台) */}
      {activeWorkspace === 'learning' && (
        <LearningWorkspacePlaceholder
          snapshot={currentSnapshot}
          currentStage={currentStage}
          maxUnlockedStage={maxUnlockedStage}
          draftText={draftsByStage[currentStage]}
          onDraftChange={(text) =>
            setDraftsByStage((prev) => ({
              ...prev,
              [currentStage]: text,
            }))
          }
          onSubmitStep={() => handleAdvanceFromCurrentStage()}
          onStepBack={handleStepBack}
          uiMode={uiMode}
          timeline={timeline}
          onRetryFromError={() => setUiMode('normal')}
          onRestoreNormalMode={() => setUiMode('normal')}
          onOpenFullDiagnosis={() => navigateWorkspace('diagnosis')}
          onOpenTransferView={() => navigateWorkspace('transfer')}
          onOpenProgressView={() => navigateWorkspace('profile')}
        />
      )}

      {/* 3. Agent Diagnostic Inspector (Agent 诊断检视器) */}
      {activeWorkspace === 'diagnosis' && (
        <DiagnosisWorkspacePlaceholder
          snapshot={currentSnapshot}
          currentStage={currentStage}
          maxUnlockedStage={maxUnlockedStage}
          uiMode={uiMode}
          timeline={timeline}
          onRetryFromError={() => setUiMode('normal')}
          onRestoreNormalMode={() => setUiMode('normal')}
          onAdvanceStage={handleAdvanceFromCurrentStage}
          onReturnToLearning={() => navigateWorkspace('learning')}
        />
      )}

      {/* 4. Transfer Verification Room (变式迁移验证室) */}
      {activeWorkspace === 'transfer' && (
        <ReviewWorkspacePlaceholder
          snapshot={currentSnapshot}
          currentStage={currentStage}
          maxUnlockedStage={maxUnlockedStage}
          uiMode={uiMode}
          timeline={timeline}
          onRetryFromError={() => setUiMode('normal')}
          onRestoreNormalMode={() => setUiMode('normal')}
          onSyncStageFromTransfer={handleSyncStageFromTransfer}
          onOpenProgressView={() => navigateWorkspace('profile')}
        />
      )}

      {/* 5. Learning Progress & Knowledge States (掌握状态与复习计划) */}
      {(activeWorkspace === 'profile' || activeWorkspace === 'review') && (
        <ProfileWorkspacePlaceholder
          currentStage={currentStage}
          maxUnlockedStage={maxUnlockedStage}
          onOpenLearningWorkspace={() => navigateWorkspace('learning')}
          onOpenTransferWorkspace={() => navigateWorkspace('transfer')}
        />
      )}
    </AppShell>
  );
};
