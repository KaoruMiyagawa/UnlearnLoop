export type WorkspaceId = 'home' | 'learning' | 'diagnosis' | 'transfer' | 'review' | 'profile';

export interface WorkspaceNavItem {
  id: WorkspaceId;
  path: string;
  label: string;
  badgeText: string;
  summary: string;
}

export const WORKSPACE_NAV_ITEMS: readonly WorkspaceNavItem[] = [
  {
    id: 'home',
    path: '/',
    label: '首页',
    badgeText: '今日',
    summary: '未结案诊断线索、待独立迁移验证任务与间隔复习焦点入口',
  },
  {
    id: 'learning',
    path: '/learning',
    label: '学习',
    badgeText: '进行中',
    summary: '脱敏题目呈现、草稿防丢、受控作答提交与实时证据侧栏联动',
  },
  {
    id: 'diagnosis',
    path: '/diagnosis',
    label: '诊断洞察',
    badgeText: '竞争假设',
    summary: '学习者原始作答不可变快照、并列错误假设、正反证据链与白名单决策解释',
  },
  {
    id: 'transfer',
    path: '/transfer',
    label: '迁移验证',
    badgeText: '防刷分',
    summary: '首次迁移失败、同题重答防刷分拦截与独立新情境题合法晋升 stable',
  },
  {
    id: 'review',
    path: '/review',
    label: '复习',
    badgeText: '待复习',
    summary: '通过服务端派发题目和真实作答验证延迟保持',
  },
  {
    id: 'profile',
    path: '/profile',
    label: '学习档案',
    badgeText: '5 主题',
    summary: '严格区分 session.status (completed) 与 KnowledgeState (stable / needs_practice) 及间隔复习执行',
  },
] as const;

export function resolveWorkspaceFromPath(pathname: string): WorkspaceId {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  const matched = WORKSPACE_NAV_ITEMS.find((item) => item.path === normalized);
  return matched ? matched.id : 'home';
}
