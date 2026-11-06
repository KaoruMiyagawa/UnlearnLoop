export type WorkspaceId = 'home' | 'learning' | 'diagnosis' | 'review' | 'profile';

export interface WorkspaceNavItem {
  id: WorkspaceId;
  path: string;
  label: string;
  summary: string;
}

export const WORKSPACE_NAV_ITEMS: readonly WorkspaceNavItem[] = [
  {
    id: 'home',
    path: '/',
    label: '首页',
    summary: '产品定位、当前连接状态与三步引导入口',
  },
  {
    id: 'learning',
    path: '/learning',
    label: '学习',
    summary: '跨学科材料、题目、答案草稿与提交工作空间（Stage 4/5 实现）',
  },
  {
    id: 'diagnosis',
    path: '/diagnosis',
    label: '诊断',
    summary: '候选错误假设、证据链、区分性追问与决策时间线（Stage 3/5 实现）',
  },
  {
    id: 'review',
    path: '/review',
    label: '复习',
    summary: '待复习队列、错误历史回溯与迁移变式验证（Stage 6 实现）',
  },
  {
    id: 'profile',
    path: '/profile',
    label: '学习档案',
    summary: '知识点状态概览、模型调用设置与本地数据控制（Stage 6 实现）',
  },
] as const;

export function resolveWorkspaceFromPath(pathname: string): WorkspaceId {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  const matched = WORKSPACE_NAV_ITEMS.find((item) => item.path === normalized);
  return matched ? matched.id : 'home';
}
