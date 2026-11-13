import type { MouseEvent } from 'react';
import { WORKSPACE_PATHS, type WorkspaceId } from '../app-shell/navigation';
import { ExamGoalSettings } from './ExamGoalSettings';
import { EXAM_VARIANT_LABELS, SKILL_AVAILABILITY_LABELS, skillEntryRoute, skills, type PlannedSkill, type SkillDefinition } from './skills';

type Navigate = (workspace: WorkspaceId) => void;

function followWorkspace(event: MouseEvent<HTMLAnchorElement>, workspace: WorkspaceId, onNavigate: Navigate) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  onNavigate(workspace);
}

function SkillCard({ skill, onNavigate }: { skill: SkillDefinition; onNavigate: Navigate }) {
  const content = <>
    <div className="learn-skill-heading">
      <h2 id={`skill-${skill.id}`} lang="en">{skill.label}</h2>
      <span className="learn-skill-localized" id={`skill-label-${skill.id}`}>{skill.localizedLabel}</span>
      <span className={`focus-state-tag learn-status-${skill.availability}`} id={`skill-status-${skill.id}`}>
        {SKILL_AVAILABILITY_LABELS[skill.availability]}
      </span>
    </div>
    <p>{skill.description}</p>
  </>;

  if (skill.availability === 'unavailable') {
    return <article className="focus-card focus-card-quiet learn-skill-card">{content}</article>;
  }

  const action = skill.availability === 'implemented' ? '进入阅读' : '查看计划';
  return <a
    className={`focus-card focus-card-quiet learn-skill-card ${skill.availability}`}
    href={skillEntryRoute(skill)}
    aria-labelledby={`skill-${skill.id} skill-label-${skill.id} skill-status-${skill.id} skill-action-${skill.id}`}
    onClick={event => followWorkspace(event, skill.workspace, onNavigate)}
  >
    {content}
    <span className="learn-skill-action" id={`skill-action-${skill.id}`}>
      {action} <span aria-hidden="true">→</span>
    </span>
  </a>;
}

export function LearnHome({ onNavigate }: { onNavigate: Navigate }) {
  return <div className="learn-page">
    <header className="verbatrail-home-hero">
      <div>
        <p className="focus-eyebrow" lang="en">Learn</p>
        <h1 data-workspace-heading tabIndex={-1}>IELTS 学习中心</h1>
        <p>选择一项技能，进入练习或查看学习计划。</p>
      </div>
    </header>
    <section className="learn-skill-grid" aria-label="IELTS 四项技能">
      {skills.map(skill => <SkillCard key={skill.id} skill={skill} onNavigate={onNavigate} />)}
    </section>
    <ExamGoalSettings />
  </div>;
}

export function PlannedSkillPage({ skill, onNavigate }: { skill: PlannedSkill; onNavigate: Navigate }) {
  return <div className="learn-page learn-skill-page">
    <a className="focus-button-quiet learn-back-link" href={WORKSPACE_PATHS.home} onClick={event => followWorkspace(event, 'home', onNavigate)}>
      <span aria-hidden="true">←</span> 返回 Learn
    </a>
    <header className="focus-page-header">
      <span className="focus-state-tag">{SKILL_AVAILABILITY_LABELS[skill.availability]}</span>
      <h1 className="focus-page-title" data-workspace-heading tabIndex={-1}><span lang="en">{skill.label}</span> · {skill.localizedLabel}</h1>
      <p className="focus-page-subtitle">{skill.description}</p>
    </header>
    <section className="focus-card focus-card-quiet" aria-labelledby="planned-capabilities">
      <h2 className="focus-card-heading" id="planned-capabilities">计划支持</h2>
      <p className="focus-card-copy" lang="en">{skill.examVariants.map(variant => EXAM_VARIANT_LABELS[variant]).join(' / ')}</p>
      <ul className="learn-capability-list">
        {skill.plannedCapabilities.map(capability => <li key={capability}>{capability}</li>)}
      </ul>
    </section>
  </div>;
}
