import React, { useState } from 'react';
import { WORKSPACE_NAV_ITEMS, WorkspaceId } from './navigation';
import {
  INITIAL_LOOP_STAGE_SNAPSHOTS,
  LoopStageId,
  UiSimulationMode,
} from '../design-system/stage5WorkbenchModel';

interface AppShellProps {
  activeWorkspace: WorkspaceId;
  onSelectWorkspace: (workspace: WorkspaceId) => void;
  backendConnected: boolean | null;
  currentStage?: LoopStageId;
  maxUnlockedStage?: LoopStageId;
  onSelectStage?: (stage: LoopStageId) => void;
  stageGuardAlert?: string | null;
  onDismissGuardAlert?: () => void;
  uiMode?: UiSimulationMode;
  onChangeUiMode?: (mode: UiSimulationMode) => void;
  onResetProgression?: () => void;
  children: React.ReactNode;
}

const LOOP_STAGE_IDS: readonly LoopStageId[] = [1, 2, 3, 4, 5, 6];

export const AppShell: React.FC<AppShellProps> = ({
  activeWorkspace,
  onSelectWorkspace,
  backendConnected,
  currentStage = 2,
  maxUnlockedStage = 2,
  onSelectStage,
  stageGuardAlert,
  onDismissGuardAlert,
  uiMode = 'normal',
  onChangeUiMode,
  onResetProgression,
  children,
}) => {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const handleNavClick = (id: WorkspaceId) => {
    onSelectWorkspace(id);
    setMobileNavOpen(false);
  };

  return (
    <div className="wb-shell">
      {/* Left Persistent Dark Product Navigation Rail (Scheme B Signature) */}
      <aside className="wb-sidebar" aria-label="UnlearnLoop 产品主导航">
        <div>
          <div className="wb-brand-box">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <a
                href="/"
                className="wb-brand-logo"
                onClick={(e) => {
                  e.preventDefault();
                  handleNavClick('home');
                }}
              >
                <span className="wb-brand-icon" aria-hidden="true">
                  UL
                </span>
                <span>UnlearnLoop</span>
              </a>
              <button
                type="button"
                onClick={() => setMobileNavOpen((prev) => !prev)}
                className="wb-btn sm lg:hidden"
                style={{
                  background: '#1E293B',
                  color: '#F8FAFC',
                  borderColor: '#334155',
                }}
              >
                {mobileNavOpen ? '收起菜单' : '导航菜单'}
              </button>
            </div>
            <span className="wb-scheme-sub">
              方案 B · Modern Product / Precision Workbench
            </span>
          </div>

          <nav
            className={`wb-rail-nav ${mobileNavOpen ? 'block' : 'hidden lg:grid'}`}
            aria-label="主工作区切换"
          >
            {WORKSPACE_NAV_ITEMS.map((item) => {
              const isActive =
                item.id === activeWorkspace ||
                (activeWorkspace === 'review' && item.id === 'profile');

              let dynamicBadge = item.badgeText;
              if (item.id === 'learning') {
                dynamicBadge = `Step ${currentStage}/6`;
              } else if (item.id === 'diagnosis') {
                const hypCount =
                  INITIAL_LOOP_STAGE_SNAPSHOTS[currentStage].hypotheses.length;
                dynamicBadge = `${hypCount} 假设`;
              }

              return (
                <button
                  key={item.id}
                  type="button"
                  aria-current={isActive ? 'page' : undefined}
                  onClick={() => handleNavClick(item.id)}
                  className={`wb-rail-btn ${isActive ? 'active' : ''}`}
                >
                  <span>{item.label}</span>
                  <span className="wb-rail-badge">{dynamicBadge}</span>
                </button>
              );
            })}
          </nav>
        </div>

        <div className="wb-rail-footer">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
            <strong style={{ color: '#F8FAFC' }}>[MOCK DATA · 正式前端]</strong>
            {backendConnected === true && (
              <span className="wb-rail-badge" style={{ background: '#065F46', color: '#A7F3D0' }}>
                API 在线
              </span>
            )}
            {backendConnected === false && (
              <span className="wb-rail-badge" style={{ background: '#334155', color: '#CBD5E1' }}>
                本地沙盒
              </span>
            )}
            {backendConnected === null && (
              <span className="wb-rail-badge">检测中…</span>
            )}
          </div>
          <div>
            三栏高密度结构：左轨导航 + 顶部受控状态机进度条 + 主操作区与实时证据侧栏。
          </div>
          <div style={{ fontSize: 11, color: '#64748B' }}>
            禁止通过 UI 越权跳过未完成的诊断或迁移验证步骤；状态流转严格受服务端领域状态机与证据链约束。
          </div>
        </div>
      </aside>

      {/* Right Main Area: Sticky Closed-Loop Header + Workbench Body */}
      <div className="wb-main-area">
        <header className="wb-top-header">
          <div className="wb-top-row">
            <div className="wb-stepper-bar" role="group" aria-label="六步闭环领域状态机进度">
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: 'var(--text-muted)',
                  marginRight: 4,
                }}
              >
                闭环状态机（不可越级跳过）：
              </span>
              {LOOP_STAGE_IDS.map((stepId) => {
                const cfg = INITIAL_LOOP_STAGE_SNAPSHOTS[stepId];
                const isCurrent = stepId === currentStage;
                const isUnlocked = stepId <= maxUnlockedStage;
                const isCompleted = stepId < currentStage || (stepId <= maxUnlockedStage && !isCurrent);

                let stateClass = '';
                if (isCurrent) stateClass = 'active';
                else if (isCompleted) stateClass = 'done';
                else if (!isUnlocked) stateClass = 'locked';

                return (
                  <button
                    key={stepId}
                    type="button"
                    onClick={() => onSelectStage && onSelectStage(stepId)}
                    className={`wb-step-pill ${stateClass}`}
                    title={
                      isUnlocked
                        ? `查看或返回已解锁阶段：${cfg.stageTitle}`
                        : `🔒 阶段尚未解锁：请先在工作台完成前置作答、追问或迁移验证`
                    }
                  >
                    <span>
                      {!isUnlocked ? '🔒 ' : isCompleted && !isCurrent ? '✓ ' : ''}
                      {cfg.shortLabel}
                    </span>
                  </button>
                );
              })}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className="wb-badge purple" title="当前使用明确标识的 Stage 5 交互式 Mock 数据源">
                数据源：[MOCK DATA]
              </span>
              <span className="wb-badge slate">
                引擎：Demo / Mock (<code>FakeModelProvider</code>)
              </span>
            </div>
          </div>

          {/* Interactive UI State Simulator Bar (Normal / Loading / Empty / Error & Retry) */}
          {onChangeUiMode && (
            <div
              className="wb-top-row"
              style={{
                paddingTop: 8,
                borderTop: '1px dashed var(--border-default)',
                fontSize: 12,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 700, color: 'var(--text-secondary)' }}>
                  界面完备状态演练：
                </span>
                {(
                  [
                    { id: 'normal', label: '● 正常交互态 (Interactive)' },
                    { id: 'loading', label: '⏳ 加载锁定态 (Loading)' },
                    { id: 'empty', label: '∅ 空数据引导态 (Empty)' },
                    { id: 'error', label: '⚠️ 超时错误与重试 (retry_waiting)' },
                  ] as const
                ).map((modeItem) => (
                  <button
                    key={modeItem.id}
                    type="button"
                    onClick={() => onChangeUiMode(modeItem.id)}
                    className={`wb-btn sm ${uiMode === modeItem.id ? 'primary' : ''}`}
                  >
                    {modeItem.label}
                  </button>
                ))}
              </div>

              {onResetProgression && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ color: 'var(--text-muted)' }}>
                    当前最高已解锁：第 {maxUnlockedStage} / 6 步
                  </span>
                  <button type="button" className="wb-btn sm" onClick={onResetProgression}>
                    重置为第 1 步初始作答状态
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Guardrail Alert when Learner Attempts to Skip Ahead in the State Machine */}
          {stageGuardAlert && (
            <div
              role="alert"
              style={{
                padding: '9px 14px',
                borderRadius: 8,
                background: 'var(--warning-soft)',
                border: '1px solid #FDE68A',
                color: 'var(--warning)',
                fontSize: 12.5,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
              }}
            >
              <span>
                <strong>🔒 领域状态机越级拦截：</strong> {stageGuardAlert}
              </span>
              {onDismissGuardAlert && (
                <button type="button" className="wb-btn sm" onClick={onDismissGuardAlert}>
                  知道了
                </button>
              )}
            </div>
          )}
        </header>

        <main className="wb-body">{children}</main>
      </div>
    </div>
  );
};
