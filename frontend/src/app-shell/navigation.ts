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
    label: '学习焦点总览',
    badgeText: '今日',
    summary: '未结案诊断线索、待独立迁移验证任务与间隔复习焦点入口',
  },
  {
    id: 'learning',
    path: '/learning',
    label: '双栏学习工作台',
    badgeText: '进行中',
    summary: '脱敏题目呈现、草稿防丢、受控作答提交与实时证据侧栏联动',
  },
  {
    id: 'diagnosis',
    path: '/diagnosis',
    label: 'Agent 诊断检视器',
    badgeText: '竞争假设',
    summary: '学习者原始作答不可变快照、并列错误假设、正反证据链与白名单决策解释',
  },
  {
    id: 'transfer',
    path: '/transfer',
    label: '变式迁移验证室',
    badgeText: '防刷分',
    summary: '首次迁移失败、同题重答防刷分拦截与独立新情境题合法晋升 stable',
  },
  {
    id: 'profile',
    path: '/profile',
    label: '掌握状态与复习计划',
    badgeText: '5 主题',
    summary: '严格区分 session.status (completed) 与 KnowledgeState (stable / needs_practice) 及间隔复习执行',
  },
] as const;

export function resolveWorkspaceFromPath(pathname: string): WorkspaceId {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  if (normalized === '/review') {
    return 'profile';
  }
  const matched = WORKSPACE_NAV_ITEMS.find((item) => item.path === normalized);
  return matched ? matched.id : 'home';
}
