import { apiRequest } from './client';

export interface LearnerEvidence {
  evidence_type: string;
  evidence_source: string;
  evidence_reference: string;
  evidence_validity: string;
  evaluation_method: string;
  content_version: string | null;
  observed_at: string;
  observation: string;
}
export interface LearnerSkill {
  skill_id: string;
  assessment_status: 'not_assessed' | 'observed';
  has_learning_record: boolean;
  evidence_levels: string[];
  evidence: LearnerEvidence[];
  limitations: string[];
}
export interface LearnerModel { skills: LearnerSkill[] }
export function getLearnerModel(learnerId: string, signal: AbortSignal): Promise<LearnerModel> {
  return apiRequest(`/api/v1/learner-model?learner_id=${encodeURIComponent(learnerId)}`, { signal });
}
