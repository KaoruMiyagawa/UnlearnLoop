import type { ExamVariant } from '../api/types.ts';
import { WORKSPACE_PATHS, type PlannedSkillWorkspace } from '../app-shell/navigation.ts';

export type SkillId = 'listening' | 'speaking' | 'reading' | 'writing';
export type SkillAvailability = 'implemented' | 'planned' | 'unavailable';

type SkillDetails = {
  id: SkillId;
  label: string;
  localizedLabel: string;
  description: string;
  examVariants: readonly ExamVariant[];
};

export type PlannedSkill = SkillDetails & {
  availability: 'planned';
  workspace: PlannedSkillWorkspace;
  availableCapabilities: readonly [];
  plannedCapabilities: readonly string[];
};

export type SkillDefinition = PlannedSkill | (SkillDetails & (
  | { availability: 'implemented'; workspace: 'learning' | PlannedSkillWorkspace; availableCapabilities: readonly string[] }
  | { availability: 'unavailable'; availableCapabilities: readonly [] }
));

const examVariants = ['academic', 'general_training'] as const;

export const SKILLS = {
  listening: {
    id: 'listening',
    label: 'Listening',
    localizedLabel: '听力',
    description: '练习捕捉关键信息，理解语境与细节。',
    availability: 'implemented',
    workspace: 'listening',
    examVariants,
    availableCapabilities: ['原创音频播放', '听力选择题', '服务端评分与逐题解释', '音频时间锚点', '共享学习历史'],
  },
  speaking: {
    id: 'speaking',
    label: 'Speaking',
    localizedLabel: '口语',
    description: '围绕熟悉与陌生话题，组织清楚连贯的表达。',
    availability: 'implemented',
    workspace: 'speaking',
    examVariants,
    availableCapabilities: ['原创 Part 1 问题', '本地录音与回放', '自主检查', '版本比较', '共享学习历史'],
  },
  reading: {
    id: 'reading',
    label: 'Reading',
    localizedLabel: '阅读',
    description: '用原创阅读材料练习判断题与段落标题匹配。',
    availability: 'implemented',
    workspace: 'learning',
    examVariants,
    availableCapabilities: ['TFNG', 'Matching Headings', '作答与评价', '诊断与专项训练', '独立迁移', '首轮延迟复习', '学习历史'],
  },
  writing: {
    id: 'writing',
    label: 'Writing',
    localizedLabel: '写作',
    description: '完成一套原创 Task 2 练习，从草稿到修订。',
    availability: 'implemented',
    workspace: 'writing',
    examVariants,
    availableCapabilities: ['原创 Task 2 题目', '草稿自动保存', '基础文本检测', '提交版本比较', '共享学习历史'],
  },
} as const satisfies { [Id in SkillId]: SkillDefinition & { id: Id } };

export const skills: readonly SkillDefinition[] = Object.values(SKILLS);
export const plannedSkills = skills.filter(skill => skill.availability === 'planned');

export const SKILL_AVAILABILITY_LABELS: Record<SkillAvailability, string> = {
  implemented: '可练习',
  planned: '规划中',
  unavailable: '暂不可用',
};

export const EXAM_VARIANT_LABELS: Partial<Record<ExamVariant, string>> = {
  academic: 'Academic',
  general_training: 'General Training',
};

export function skillEntryRoute(skill: Exclude<SkillDefinition, { availability: 'unavailable' }>) {
  return WORKSPACE_PATHS[skill.workspace];
}
