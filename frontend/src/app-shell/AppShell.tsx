import React, { useEffect, useRef } from 'react';
import { isLearnWorkspace, WORKSPACE_SHORTCUTS, type WorkspaceId } from './navigation';
import { UiSimulationMode } from '../design-system/stage5WorkbenchModel';
import { useTheme } from '../design-system/ThemeProvider';

interface AppShellProps {
  activeWorkspace: WorkspaceId;
  onSelectWorkspace: (workspace: WorkspaceId) => void;
  backendConnected: boolean | null;
  dataMode: 'demo' | 'real';
  onChangeDataMode: (mode: 'demo' | 'real') => void;
  hasDiagnosticCase?: boolean;
  currentStage?: 1 | 2 | 3 | 4 | 5 | 6;
  maxUnlockedStage?: 1 | 2 | 3 | 4 | 5 | 6;
  onSelectStage?: (stage: 1 | 2 | 3 | 4 | 5 | 6) => void;
  stageGuardAlert?: string | null;
  onDismissGuardAlert?: () => void;
  uiMode?: UiSimulationMode;
  onChangeUiMode?: (mode: UiSimulationMode) => void;
  onResetProgression?: () => void;
  children: React.ReactNode;
}

const SIMULATION_MODES: readonly { id: UiSimulationMode; label: string }[] = [
  { id: 'normal', label: '正常状态' },
  { id: 'loading', label: '加载状态' },
  { id: 'empty', label: '空状态' },
  { id: 'error', label: '错误恢复' },
];

export const AppShell: React.FC<AppShellProps> = (props) => {
  const { theme, toggleTheme } = useTheme();
  const {
    activeWorkspace,
    onSelectWorkspace,
    backendConnected,
    dataMode,
    onChangeDataMode,
    uiMode = 'normal',
    onChangeUiMode,
    onResetProgression,
    children,
  } = props;
  const main = useRef<HTMLElement>(null);
  const previousWorkspace = useRef(activeWorkspace);

  useEffect(() => {
    const previous = previousWorkspace.current;
    previousWorkspace.current = activeWorkspace;
    if (previous === activeWorkspace || !isLearnWorkspace(activeWorkspace)) return;
    if (activeWorkspace === 'learning' && !isLearnWorkspace(previous)) return;
    main.current?.querySelector<HTMLElement>('[data-workspace-heading]')?.focus({ preventScroll: true });
  }, [activeWorkspace]);

  return (
    <div className="focus-app">
      <header className="focus-top-nav">
        <div className="focus-top-nav-inner">
          <button
            type="button"
            className="focus-brand"
            onClick={() => onSelectWorkspace('home')}
            aria-label="VerbaTrail · Learn"
          >
            <span className="focus-brand-mark" aria-hidden="true">V</span>
            <span>VerbaTrail</span>
          </button>

          <nav className="focus-product-nav" aria-label="产品导航">
            <button
              type="button"
              className={`focus-nav-tab${isLearnWorkspace(activeWorkspace) ? ' active' : ''}`}
              aria-current={activeWorkspace === 'home' ? 'page' : isLearnWorkspace(activeWorkspace) ? 'true' : undefined}
              onClick={() => onSelectWorkspace('home')}
            >
              <span lang="en">Learn</span>
            </button>
            <span className="focus-product-planned"><span lang="en">Discover</span><small>规划中</small></span>
            <span className="focus-product-planned"><span lang="en">Adapt</span><small>规划中</small></span>
          </nav>

          <nav className="focus-nav-links" aria-label="学习工具">
            {WORKSPACE_SHORTCUTS.map((item) => {
              const active = item.id === activeWorkspace;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`focus-nav-tab${active ? ' active' : ''}`}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => onSelectWorkspace(item.id)}
                >
                  {item.label}
                </button>
              );
            })}
          </nav>

          <div className="focus-nav-tools">
            <button type="button" className="focus-theme-toggle" onClick={toggleTheme} aria-label={`切换至${theme === 'premium' ? '曜黑香槟金' : '深海蓝暖纸白'}主题`} aria-pressed={theme === 'noir'} title={`当前：${theme === 'premium' ? 'Premium Academic' : 'Noir & Champagne'}；切换主题`}>
              <span aria-hidden="true">{theme === 'premium' ? '☾' : '☼'}</span><span>{theme === 'premium' ? '曜黑' : '暖白'}</span>
            </button>
            <div className="focus-mode-switch" role="group" aria-label="数据模式">
              <button
                type="button"
                aria-pressed={dataMode === 'real'}
                className={dataMode === 'real' ? 'selected' : ''}
                onClick={() => onChangeDataMode('real')}
              >
                真实
              </button>
              <button
                type="button"
                aria-pressed={dataMode === 'demo'}
                className={dataMode === 'demo' ? 'selected' : ''}
                onClick={() => onChangeDataMode('demo')}
              >
                演示
              </button>
            </div>
            <span
              className={`focus-health-dot ${backendConnected === true ? 'online' : backendConnected === false ? 'offline' : 'checking'}`}
              role="status"
              aria-label={backendConnected === true ? '后端健康检查在线' : backendConnected === false ? '后端不可用' : '正在检查后端'}
              title={backendConnected === true ? '后端健康检查在线；这不代表 Agent 已运行' : backendConnected === false ? '后端健康检查失败' : '正在检查后端'}
            />
          </div>
        </div>

        {dataMode === 'demo' && onChangeUiMode && (
          <details className="focus-demo-tools">
            <summary>演示界面状态</summary>
            <div className="focus-demo-tools-content">
              {SIMULATION_MODES.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  className={uiMode === mode.id ? 'selected' : ''}
                  aria-pressed={uiMode === mode.id}
                  onClick={() => onChangeUiMode(mode.id)}
                >
                  {mode.label}
                </button>
              ))}
              {onResetProgression && <button type="button" onClick={onResetProgression}>重置演示</button>}
            </div>
          </details>
        )}
      </header>

      <main ref={main} className={`focus-stage ${activeWorkspace === 'learning' || activeWorkspace === 'transfer' ? 'focus-stage-wide' : ''}`}>
        {children}
      </main>
    </div>
  );
};
