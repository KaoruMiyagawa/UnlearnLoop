import React, { useState } from 'react';
import { WORKSPACE_NAV_ITEMS, WorkspaceId } from './navigation';
import { StatusBadge } from '../design-system/StatusBadge';

interface AppShellProps {
  activeWorkspace: WorkspaceId;
  onSelectWorkspace: (workspace: WorkspaceId) => void;
  backendConnected: boolean | null;
  children: React.ReactNode;
}

export const AppShell: React.FC<AppShellProps> = ({
  activeWorkspace,
  onSelectWorkspace,
  backendConnected,
  children,
}) => {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const handleNavClick = (id: WorkspaceId) => {
    onSelectWorkspace(id);
    setMobileNavOpen(false);
  };

  return (
    <div className="min-h-screen bg-surface-page text-text-primary">
      {/* Top Brand Header */}
      <header className="sticky top-0 z-20 border-b border-border-default bg-surface-raised">
        <div className="mx-auto flex h-16 max-w-stage items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <span
              aria-hidden="true"
              className="grid h-8 w-8 place-items-center rounded-control bg-action-primary text-xs font-semibold text-white"
            >
              UL
            </span>
            <div>
              <span className="text-base font-semibold tracking-tight text-text-primary">
                UnlearnLoop
              </span>
              <span className="ml-2 hidden text-xs text-text-secondary sm:inline">
                错误诊断优先的自适应学习系统 · Stage 1 基线
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden sm:block">
              {backendConnected === null && (
                <StatusBadge tone="primary" label="API 检查中" />
              )}
              {backendConnected === true && (
                <StatusBadge tone="success" label="API 在线" />
              )}
              {backendConnected === false && (
                <StatusBadge tone="error" label="API 离线" />
              )}
            </div>

            {/* Mobile expandable navigation toggle (DESIGN_SYSTEM.md 3.1) */}
            <button
              type="button"
              aria-expanded={mobileNavOpen}
              aria-controls="mobile-primary-nav"
              onClick={() => setMobileNavOpen((prev) => !prev)}
              className="h-10 rounded-control border border-border-default bg-surface-raised px-3 text-sm font-semibold text-text-primary hover:bg-surface-subtle focus:outline-none focus:ring-2 focus:ring-action-primary lg:hidden"
            >
              {mobileNavOpen ? '收起导航' : '展开导航'}
            </button>
          </div>
        </div>

        {/* Mobile Expandable Navigation Drawer */}
        {mobileNavOpen && (
          <nav
            id="mobile-primary-nav"
            aria-label="移动端主导航"
            className="border-t border-border-default bg-surface-raised px-4 py-3 lg:hidden"
          >
            <ul className="space-y-1">
              {WORKSPACE_NAV_ITEMS.map((item) => {
                const isActive = item.id === activeWorkspace;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      aria-current={isActive ? 'page' : undefined}
                      onClick={() => handleNavClick(item.id)}
                      className={`flex w-full items-center justify-between rounded-control px-3 py-2.5 text-left text-sm font-semibold transition ${
                        isActive
                          ? 'bg-blue-50 text-action-primary'
                          : 'text-text-secondary hover:bg-surface-subtle hover:text-text-primary'
                      }`}
                    >
                      <span>{item.label}</span>
                      {isActive && (
                        <span className="text-xs font-normal text-action-primary">
                          当前工作空间
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
        )}
      </header>

      {/* Main Responsive Stage: Desktop left navigation + primary column (max 1200px) */}
      <div className="mx-auto flex max-w-stage flex-col gap-6 px-4 py-6 sm:px-6 lg:flex-row lg:items-start lg:py-8">
        <aside className="hidden w-56 shrink-0 lg:block">
          <nav
            aria-label="桌面端主导航"
            className="rounded-control border border-border-default bg-surface-raised p-3"
          >
            <p className="px-3 pb-2 text-xs font-semibold uppercase tracking-wider text-text-secondary">
              工作空间导航
            </p>
            <ul className="space-y-1">
              {WORKSPACE_NAV_ITEMS.map((item) => {
                const isActive = item.id === activeWorkspace;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      aria-current={isActive ? 'page' : undefined}
                      onClick={() => handleNavClick(item.id)}
                      className={`flex w-full items-center justify-between rounded-control px-3 py-2.5 text-left text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-action-primary ${
                        isActive
                          ? 'bg-blue-50 text-action-primary'
                          : 'text-text-secondary hover:bg-surface-subtle hover:text-text-primary'
                      }`}
                    >
                      <span>{item.label}</span>
                      {isActive && (
                        <span
                          aria-hidden="true"
                          className="h-2 w-2 rounded-full bg-action-primary"
                        />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
        </aside>

        <main className="min-w-0 flex-1 space-y-6">{children}</main>
      </div>
    </div>
  );
};
