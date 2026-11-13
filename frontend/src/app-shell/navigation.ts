export type PlannedSkillWorkspace = 'listening' | 'speaking' | 'writing';
export type WorkspaceId = 'home' | 'learning' | PlannedSkillWorkspace | 'diagnosis' | 'transfer' | 'review' | 'profile';

export const WORKSPACE_PATHS = {
  home: '/',
  learning: '/learning',
  listening: '/learn/listening',
  speaking: '/learn/speaking',
  writing: '/learn/writing',
  diagnosis: '/diagnosis',
  transfer: '/transfer',
  review: '/review',
  profile: '/profile',
} as const satisfies Record<WorkspaceId, string>;

export const WORKSPACE_SHORTCUTS = [
  { id: 'learning', label: '阅读' },
  { id: 'diagnosis', label: '诊断洞察' },
  { id: 'transfer', label: '迁移验证' },
  { id: 'review', label: '复习' },
  { id: 'profile', label: '学习档案' },
] as const;

export function isLearnWorkspace(workspace: WorkspaceId): boolean {
  return workspace === 'home' || workspace === 'learning' || WORKSPACE_PATHS[workspace].startsWith('/learn/');
}

export function resolveWorkspaceFromPath(pathname: string): WorkspaceId {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  if (normalized === '/learn/reading') return 'learning';
  return (Object.keys(WORKSPACE_PATHS) as WorkspaceId[]).find(id => WORKSPACE_PATHS[id] === normalized) ?? 'home';
}
