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
    availability: 'planned',
    workspace: 'speaking',
    examVariants,
    availableCapabilities: [],
    plannedCapabilities: ['IELTS Speaking Part 1 / 2 / 3', '口语模拟练习', '录音与转写', '表达反馈与 AI 口语评价'],
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
    description: '按考试类型练习写作任务，从草稿到修改。',
    availability: 'planned',
    workspace: 'writing',
    examVariants,
    availableCapabilities: [],
    plannedCapabilities: ['Academic / General Training 对应写作任务', 'Writing Task 1 / 2', '草稿与修改', '结构、语言与任务完成度反馈'],
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
