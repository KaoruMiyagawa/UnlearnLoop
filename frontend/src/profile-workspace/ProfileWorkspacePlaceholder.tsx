import React, { useState } from 'react';
import {
  INITIAL_TOPIC_MASTERY_MATRIX,
  LoopStageId,
  TopicMasteryMatrixItem,
} from '../design-system/stage5WorkbenchModel';

interface ProfileWorkspacePlaceholderProps {
  currentStage?: LoopStageId;
  maxUnlockedStage?: LoopStageId;
  onOpenLearningWorkspace?: () => void;
  onOpenTransferWorkspace?: () => void;
}

export const ProfileWorkspacePlaceholder: React.FC<
  ProfileWorkspacePlaceholderProps
> = ({
  currentStage = 2,
  maxUnlockedStage = 2,
  onOpenLearningWorkspace,
  onOpenTransferWorkspace,
}) => {
  const [topics, setTopics] = useState<TopicMasteryMatrixItem[]>(
    INITIAL_TOPIC_MASTERY_MATRIX,
  );
  const [semanticBanner, setSemanticBanner] = useState<string | null>(null);

  const isPyLoopMastered = maxUnlockedStage >= 6 || currentStage === 6;

  const computedTopics = topics.map((t) => {
    if (t.topicSlug !== 'py-for-loop') return t;
    if (isPyLoopMastered) {
      return {
        ...t,
        sessionStatus: 'completed' as const,
        knowledgeStatus: 'stable' as const,
        topicMastered: true,
        completionReason: 'mastery_achieved',
        confidenceScore: 0.90,
        lastEvidenceSummary:
          '已完成第 6 步：独立新迁移题 q_py_loop_transfer_02 (#att_06) 首次验证通过 · 合法晋升 stable',
      };
    }
    return t;
  });

  const handleCompleteSessionWithoutMastery = () => {
    setTopics((prev) =>
      prev.map((item) => {
        if (item.topicSlug !== 'py-for-loop') return item;
        return {
          ...item,
          sessionStatus: 'completed',
          knowledgeStatus: 'needs_practice',
          topicMastered: false,
          completionReason: 'session_completed_without_mastery',
          lastEvidenceSummary:
            '学习者在未通过独立新题迁移验证前主动调用 POST /api/v1/sessions/{id}/complete：session.status=completed，但 topic_mastered=false (保持 needs_practice)',
        };
      }),
    );
    setSemanticBanner(
      '[Mock 状态演示] 已演示 Stage 4/5 会话结束语义边界：py-for-loop 的 session.status 已模拟更新为 "completed"（会话已结束），但因为缺少独立新题迁移验证证据，KnowledgeState 保持为 "needs_practice" 且 topic_mastered = false（正式对应接口：POST /api/v1/sessions/{id}/complete）。',
    );
  };

  const handleCompleteSpacedReview = (topicSlug: string) => {
    setTopics((prev) =>
      prev.map((item) => {
        if (item.topicSlug !== topicSlug) return item;
        return {
          ...item,
          reviewDueStatus: 'completed',
          lastEvidenceSummary: `${item.lastEvidenceSummary} · [已模拟完成今日间隔复习 POST /api/v1/reviews/${item.reviewItemId}/complete]`,
        };
      }),
    );
    setSemanticBanner(
      `[Mock 状态演示] 已模拟完成知识点 ${topicSlug} 的到期复习任务（ReviewItem 状态更新为 completed，正式对应接口：POST /api/v1/reviews/{id}/complete）。`,
    );
  };

  const dueReviews = computedTopics.filter((t) => t.reviewDueStatus === 'due_now');

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 16,
          flexWrap: 'wrap',
          marginBottom: 18,
        }}
      >
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--action-primary)' }}>
            KNOWLEDGE STATE & SESSION COMPLETION SEMANTICS · 学习进度与知识状态
          </div>
          <h1 style={{ margin: '2px 0 4px', fontSize: 22, fontWeight: 700 }}>
            知识点掌握状态矩阵与间隔复习队列
          </h1>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: 13.5 }}>
            严格区分 <code>session.status == "completed"</code>（会话已结束）与{' '}
            <code>KnowledgeState.status == "stable"</code>（当前阶段操作性掌握，<code>topic_mastered=true</code>）。
          </p>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {!isPyLoopMastered && (
            <button
              type="button"
              className="wb-btn sm"
              onClick={handleCompleteSessionWithoutMastery}
            >
              模拟未掌握时主动结束会话 (session_completed_without_mastery)
            </button>
          )}
          {onOpenLearningWorkspace && (
            <button type="button" className="wb-btn primary sm" onClick={onOpenLearningWorkspace}>
              返回双栏学习工作台 →
            </button>
          )}
        </div>
      </div>

      {semanticBanner && (
        <div
          role="status"
          style={{
            padding: '12px 16px',
            marginBottom: 18,
            borderRadius: 10,
            background: 'var(--action-soft)',
            border: '1px solid #BFDBFE',
            color: 'var(--action-primary)',
            fontSize: 13,
          }}
        >
          <strong>✓ 状态更新反馈：</strong> {semanticBanner}
        </div>
      )}

      {/* 1. Orthogonal Semantics Comparison Card */}
      <section className="wb-card" aria-labelledby="semantics-matrix-heading">
        <div className="wb-card-head">
          <div>
            <h2 id="semantics-matrix-heading" className="wb-card-title">
              Python 基础内容包 · 5 大知识点掌握度与会话结束语义对照表
            </h2>
          </div>
          <span className="wb-badge slate">
            所有权重均显式标记 <code>confidence_is_heuristic = true</code>（非统计概率）
          </span>
        </div>

        <div className="wb-card-body" style={{ display: 'grid', gap: 12 }}>
          {computedTopics.map((topic) => {
            const masteryBadgeTone =
              topic.knowledgeStatus === 'stable'
                ? 'green'
                : topic.knowledgeStatus === 'needs_practice'
                  ? 'amber'
                  : 'slate';

            const sessionBadgeTone =
              topic.sessionStatus === 'completed'
                ? 'slate'
                : topic.sessionStatus === 'paused'
                  ? 'purple'
                  : 'blue';

            return (
              <div
                key={topic.topicSlug}
                style={{
                  padding: '14px 16px',
                  borderRadius: 10,
                  border: '1px solid var(--border-default)',
                  background: '#FAFBFD',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 14,
                  flexWrap: 'wrap',
                }}
              >
                <div style={{ maxWidth: 720 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <strong style={{ fontSize: 14.5 }}>
                      <code>{topic.topicSlug}</code> · {topic.topicTitle}
                    </strong>
                    {topic.prerequisiteSlugs.length > 0 && (
                      <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                        前置依赖：{topic.prerequisiteSlugs.join(', ')}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 4 }}>
                    {topic.lastEvidenceSummary}
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 4 }}>
                    结束语义码：<code>{topic.completionReason}</code> · 启发式掌握度参考指标：{' '}
                    <code>{Math.round(topic.confidenceScore * 100)}%</code> (
                    <code>confidence_is_heuristic=true</code>)
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span className={`wb-badge ${sessionBadgeTone}`}>
                    Session: {topic.sessionStatus}
                  </span>
                  <span className={`wb-badge ${masteryBadgeTone}`}>
                    Mastery: {topic.knowledgeStatus} (topic_mastered={String(topic.topicMastered)})
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 2. Spaced Review Queue Card */}
      <section className="wb-card" aria-labelledby="review-queue-heading">
        <div className="wb-card-head">
          <div>
            <h2 id="review-queue-heading" className="wb-card-title">
              按错误模式与遗忘风险驱动的间隔复习队列 (ReviewItem Queue)
            </h2>
          </div>
          <span className="wb-badge red">当前到期复习：{dueReviews.length} 项</span>
        </div>

        <div className="wb-card-body" style={{ display: 'grid', gap: 12 }}>
          {computedTopics
            .filter((t) => t.reviewDueStatus !== 'none')
            .map((item) => (
              <div
                key={item.topicSlug}
                style={{
                  padding: '13px 16px',
                  borderRadius: 8,
                  border: '1px solid var(--border-default)',
                  background: 'var(--surface-page)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 12,
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <div>
                    <strong>
                      <code>{item.topicSlug}</code> · {item.topicTitle}
                    </strong>{' '}
                    {item.reviewItemId && (
                      <code style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                        ({item.reviewItemId})
                      </code>
                    )}
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 3 }}>
                    触发原因：{item.reviewReason ?? '周期巩固检验'}
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {item.reviewDueStatus === 'due_now' && (
                    <>
                      <span className="wb-badge red">今日到期 (due_now)</span>
                      <button
                        type="button"
                        className="wb-btn primary sm"
                        onClick={() => handleCompleteSpacedReview(item.topicSlug)}
                      >
                        标记完成间隔复习 →
                      </button>
                      {onOpenTransferWorkspace && item.topicSlug === 'py-for-loop' && (
                        <button
                          type="button"
                          className="wb-btn sm"
                          onClick={onOpenTransferWorkspace}
                        >
                          进入变式迁移验证
                        </button>
                      )}
                    </>
                  )}
                  {item.reviewDueStatus === 'scheduled' && (
                    <span className="wb-badge blue">已排期明日复习</span>
                  )}
                  {item.reviewDueStatus === 'completed' && (
                    <span className="wb-badge green">✓ 今日复习已完成</span>
                  )}
                </div>
              </div>
            ))}
        </div>
      </section>
    </div>
  );
};
