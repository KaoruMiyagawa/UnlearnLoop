import React, { useState } from 'react';
import { DiagnosticInspectorRail } from '../design-system/DiagnosticInspectorRail';
import {
  DecisionTimelineItemView,
  LoopStageId,
  LoopStageSnapshot,
  UiSimulationMode,
} from '../design-system/stage5WorkbenchModel';

interface LearningWorkspacePlaceholderProps {
  snapshot?: LoopStageSnapshot;
  currentStage?: LoopStageId;
  maxUnlockedStage?: LoopStageId;
  draftText?: string;
  onDraftChange?: (text: string) => void;
  onSubmitStep?: (submittedText: string) => void;
  onStepBack?: () => void;
  uiMode?: UiSimulationMode;
  timeline?: DecisionTimelineItemView[];
  onRetryFromError?: () => void;
  onRestoreNormalMode?: () => void;
  onOpenFullDiagnosis?: () => void;
  onOpenTransferView?: () => void;
  onOpenProgressView?: () => void;
}

export const LearningWorkspacePlaceholder: React.FC<
  LearningWorkspacePlaceholderProps
> = ({
  snapshot,
  currentStage = 2,
  maxUnlockedStage = 2,
  draftText = '',
  onDraftChange,
  onSubmitStep,
  onStepBack,
  uiMode = 'normal',
  timeline = [],
  onRetryFromError = () => {},
  onRestoreNormalMode = () => {},
  onOpenFullDiagnosis,
  onOpenTransferView,
  onOpenProgressView,
}) => {
  const [showMaterial, setShowMaterial] = useState(false);
  const [unauthorizedAttemptAlert, setUnauthorizedAttemptAlert] = useState<string | null>(
    null,
  );
  const [submissionNotice, setSubmissionNotice] = useState<string | null>(null);

  if (!snapshot) {
    return null;
  }

  const isSubmittingOrLoading = uiMode === 'loading';
  const isErrorState = uiMode === 'error';
  const isEmptyState = uiMode === 'empty';

  const handlePrimarySubmit = () => {
    setUnauthorizedAttemptAlert(null);
    if (!draftText.trim()) {
      setSubmissionNotice('请先在作答输入框填写答案或点击上方快捷填入按钮后再提交。');
      return;
    }

    if (currentStage === 6 && onOpenProgressView) {
      onOpenProgressView();
      return;
    }

    setSubmissionNotice(
      `[Mock 状态演示] 已模拟提交 "${draftText.trim()}" · 界面模拟推进至第 ${Math.min(6, currentStage + 1)} 步（正式持久化与后端决策待 Stage 5C API 集成）。`,
    );
    if (onSubmitStep) {
      onSubmitStep(draftText.trim());
    }
  };

  const handleSimulateUnauthorizedQuestion = () => {
    setUnauthorizedAttemptAlert(
      `[Mock 模拟校验] 400 Bad Request / 409 Conflict (DomainRuleViolation / InvalidStateTransition)：当前会话分配的合法题目为 ${snapshot.task.questionId} (${snapshot.task.questionRole})，禁止绕过当前诊断/干预流程直接提交未授权题目！`,
    );
  };

  const visibleTimeline = timeline.filter(
    (item) => item.stageReachableAt <= maxUnlockedStage,
  );

  return (
    <div className="wb-grid">
      {/* Left Primary Task & Interaction Column */}
      <div>
        {/* 1. Primary Learning & Task Card */}
        <section className="wb-card" aria-labelledby="workspace-task-title">
          <div className="wb-card-head">
            <div>
              <div style={{ fontSize: 12, color: 'var(--action-primary)', fontWeight: 700 }}>
                {snapshot.stageTitle}
              </div>
              <h1 id="workspace-task-title" className="wb-card-title" style={{ marginTop: 2 }}>
                知识点：Python <code>for</code> 循环与状态累加器 (<code>py-for-loop</code>)
              </h1>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className="wb-badge blue">会话状态：{snapshot.sessionStatusDisplay}</span>
              <span
                className={`wb-badge ${
                  snapshot.knowledgeStatus === 'stable'
                    ? 'green'
                    : snapshot.knowledgeStatus === 'needs_practice'
                      ? 'amber'
                      : 'slate'
                }`}
              >
                掌握状态：{snapshot.knowledgeStatus}
              </span>
            </div>
          </div>

          <div className="wb-card-body">
            {/* Collapsible Learning Material & Prerequisite Context */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 10,
                flexWrap: 'wrap',
                padding: '10px 14px',
                background: 'var(--surface-subtle)',
                borderRadius: 8,
                marginBottom: 14,
                fontSize: 12.5,
              }}
            >
              <div>
                <strong>前置依赖：</strong>
                <code>py-variables-types (stable)</code> ·{' '}
                <span style={{ color: 'var(--text-secondary)' }}>
                  版本快照：<code>content_pack v1.2</code>
                </span>
              </div>
              <button
                type="button"
                className="wb-btn sm"
                onClick={() => setShowMaterial((prev) => !prev)}
              >
                {showMaterial ? '收起背景学习材料 ▲' : '查阅知识点参考材料 ▼'}
              </button>
            </div>

            {showMaterial && (
              <div
                style={{
                  padding: '14px 16px',
                  marginBottom: 16,
                  borderRadius: 8,
                  border: '1px solid var(--border-default)',
                  background: '#FAFBFD',
                  fontSize: 13,
                }}
              >
                <strong style={{ display: 'block', marginBottom: 6 }}>
                  📘 参考材料：<code>range(start, stop, step)</code> 左闭右开边界与累加器追踪
                </strong>
                <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--text-secondary)' }}>
                  <li>
                    单参数 <code>range(n)</code> 默认从 <code>0</code> 开始，生成{' '}
                    <code>0, 1, ..., n-1</code> 共 <code>n</code> 个整数。
                  </li>
                  <li>
                    双参数 <code>range(start, stop)</code> 从 <code>start</code> 开始，在到达{' '}
                    <code>stop</code> 之前停止（不包含 <code>stop</code>）。
                  </li>
                  <li>
                    追踪循环时请分别记录每一轮进入循环体时的控制变量 <code>i</code> 以及更新后的累加器{' '}
                    <code>total</code>。
                  </li>
                </ul>
              </div>
            )}

            {/* Empty State Simulation */}
            {isEmptyState ? (
              <div
                style={{
                  padding: '28px 20px',
                  borderRadius: 10,
                  border: '1px dashed var(--border-strong)',
                  background: 'var(--surface-page)',
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 6 }}>
                  当前学习工作区暂无活动会话或待答题目
                </div>
                <p
                  style={{
                    margin: '0 auto 14px',
                    maxWidth: 520,
                    fontSize: 13,
                    color: 'var(--text-secondary)',
                  }}
                >
                  此视图用于验证空数据（Empty State）下的界面降级与引导体验。点击下方按钮即可创建或恢复{' '}
                  <code>py-for-loop</code> 学习会话。
                </p>
                <button
                  type="button"
                  className="wb-btn primary"
                  onClick={onRestoreNormalMode}
                >
                  恢复 py-for-loop 活跃学习会话 →
                </button>
              </div>
            ) : (
              <>
                {/* Loading State Banner */}
                {isSubmittingOrLoading && (
                  <div
                    role="status"
                    style={{
                      padding: '12px 14px',
                      marginBottom: 14,
                      borderRadius: 8,
                      background: 'var(--action-soft)',
                      border: '1px solid #BFDBFE',
                      color: 'var(--action-primary)',
                      fontSize: 13,
                    }}
                  >
                    <strong>⏳ 正在执行受控规则评估与 Agent 诊断单步推理…</strong>
                    <div style={{ fontSize: 12, marginTop: 4 }}>
                      提交按钮与输入框已加锁保护（幂等键 <code>idempotency_key</code> 生效中），本地草稿已安全保留。
                    </div>
                  </div>
                )}

                {/* Error & Retry State Banner */}
                {isErrorState && (
                  <div
                    role="alert"
                    style={{
                      padding: '12px 14px',
                      marginBottom: 14,
                      borderRadius: 8,
                      background: 'var(--danger-soft)',
                      border: '1px solid #FECDD3',
                      color: 'var(--danger)',
                      fontSize: 13,
                    }}
                  >
                    <div style={{ fontWeight: 700 }}>
                      ⚠️ 模型单步调用失败或超时 (ErrorCode: <code>AGENT_STEP_TIMEOUT</code>)
                    </div>
                    <p style={{ margin: '4px 0 8px', color: 'var(--text-primary)', fontSize: 12.5 }}>
                      你刚才输入的草稿内容 <code>"{draftText}"</code> 已保存在本地工作区，绝不丢失。会话已进入{' '}
                      <code>retry_waiting</code> 安全状态。
                    </p>
                    <div className="wb-btn-group" style={{ marginTop: 6 }}>
                      <button type="button" className="wb-btn primary sm" onClick={onRetryFromError}>
                        立即重试当前诊断步骤 (保留草稿) →
                      </button>
                      <button type="button" className="wb-btn sm" onClick={onRestoreNormalMode}>
                        切换回正常交互态
                      </button>
                    </div>
                  </div>
                )}

                {/* Sanitized Task Prompt Box */}
                <div
                  style={{
                    padding: '13px 15px',
                    background: 'var(--surface-page)',
                    border: '1px solid var(--border-default)',
                    borderRadius: 8,
                    marginBottom: 14,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 8,
                      flexWrap: 'wrap',
                    }}
                  >
                    <strong style={{ fontSize: 13.5 }}>
                      当前合法分配任务（<code>{snapshot.task.roleLabel}</code>）
                    </strong>
                    <span className="wb-badge slate">
                      SanitizedQuestionResponse · v{snapshot.task.questionVersion}
                    </span>
                  </div>
                  <div style={{ marginTop: 6, fontSize: 14, fontWeight: 600 }}>
                    {snapshot.task.promptTitle}
                  </div>
                  <div style={{ marginTop: 4, fontSize: 12.5, color: 'var(--text-secondary)' }}>
                    {snapshot.task.promptDescription}
                  </div>
                </div>

                {/* Code Context Block */}
                <div className="wb-code-box">
                  <div className="wb-code-head">
                    <span>
                      {snapshot.task.codeLanguage} · 脱敏题目代码上下文 (已隐藏标准答案与评分正则)
                    </span>
                    <span>授权题目 ID: {snapshot.task.questionId}</span>
                  </div>
                  <pre>{snapshot.task.codeSnippet}</pre>
                </div>

                {/* Quick Preset Fill Buttons for Reviewer Convenience */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    flexWrap: 'wrap',
                    marginTop: 12,
                    marginBottom: 8,
                  }}
                >
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>
                    快捷填入典型作答证据：
                  </span>
                  {snapshot.task.recommendedInputs.map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      disabled={isSubmittingOrLoading}
                      onClick={() => {
                        if (onDraftChange) onDraftChange(preset.value);
                        setSubmissionNotice(`已填入推荐作答："${preset.value}"（${preset.hint}）`);
                      }}
                      className="wb-btn sm"
                      title={preset.hint}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>

                {/* Answer & Execution Trace Input */}
                <label
                  htmlFor="learner-answer-input"
                  style={{ display: 'block', fontWeight: 600, margin: '10px 0 6px', fontSize: 13.5 }}
                >
                  学习者当前作答 / 执行轨迹输入（支持草稿自动防丢）：
                </label>
                <textarea
                  id="learner-answer-input"
                  className="wb-textarea"
                  disabled={isSubmittingOrLoading}
                  value={draftText}
                  onChange={(e) => onDraftChange && onDraftChange(e.target.value)}
                  placeholder="请输入预测输出及每轮循环变量变化说明…"
                />

                {submissionNotice && (
                  <div
                    style={{
                      marginTop: 10,
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: 'var(--success-soft)',
                      border: '1px solid #A7F3D0',
                      color: 'var(--success)',
                      fontSize: 12.5,
                    }}
                  >
                    ✓ {submissionNotice}
                  </div>
                )}

                {unauthorizedAttemptAlert && (
                  <div
                    role="alert"
                    style={{
                      marginTop: 10,
                      padding: '9px 12px',
                      borderRadius: 6,
                      background: 'var(--danger-soft)',
                      border: '1px solid #FECDD3',
                      color: 'var(--danger)',
                      fontSize: 12.5,
                    }}
                  >
                    <strong>🚫 会话题目授权校验拦截：</strong> {unauthorizedAttemptAlert}
                  </div>
                )}

                {/* Action Button Bar */}
                <div className="wb-btn-group">
                  <button
                    type="button"
                    disabled={isSubmittingOrLoading}
                    onClick={handlePrimarySubmit}
                    className="wb-btn primary"
                  >
                    {isSubmittingOrLoading ? '提交锁保护中…' : snapshot.task.primaryActionLabel}
                  </button>

                  {currentStage > 1 && onStepBack && (
                    <button
                      type="button"
                      disabled={isSubmittingOrLoading}
                      onClick={onStepBack}
                      className="wb-btn"
                    >
                      ← 回看上一步状态 (第 {currentStage - 1} 步)
                    </button>
                  )}

                  {currentStage >= 5 && onOpenTransferView && (
                    <button
                      type="button"
                      onClick={onOpenTransferView}
                      className="wb-btn"
                    >
                      打开迁移验证防刷分专室 →
                    </button>
                  )}

                  <button
                    type="button"
                    disabled={isSubmittingOrLoading}
                    onClick={handleSimulateUnauthorizedQuestion}
                    className="wb-btn danger sm"
                    title="测试 Stage 4/5 领域安全规则：禁止提交非当前会话合法分配的题目"
                  >
                    测试越权提交非当前派发题目
                  </button>
                </div>
              </>
            )}
          </div>
        </section>

        {/* 2. Immutable DecisionEvent Audit Timeline Card */}
        <section className="wb-card" aria-labelledby="decision-timeline-title">
          <div className="wb-card-head">
            <div>
              <h2 id="decision-timeline-title" className="wb-card-title">
                决策审计时间线（DecisionEvent 不可变日志）
              </h2>
            </div>
            <span className="wb-badge slate">
              已记录 {visibleTimeline.length} 条可重放事件 · 支持按固定输入回溯
            </span>
          </div>
          <div className="wb-card-body" style={{ display: 'grid', gap: 10, fontSize: 13 }}>
            {visibleTimeline.map((evt) => (
              <div
                key={evt.eventId}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 12,
                  flexWrap: 'wrap',
                  paddingBottom: 9,
                  borderBottom: '1px solid var(--border-default)',
                }}
              >
                <div>
                  <strong>#{evt.eventId}</strong> · <code>{evt.toolName}</code> ({evt.timestamp})：
                  <span style={{ color: 'var(--text-secondary)', marginLeft: 4 }}>
                    {evt.summary}
                  </span>
                </div>
                <span className={`wb-badge ${evt.badgeTone}`}>{evt.outcomeCode}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Right Sticky Live Agent Diagnostic & Evidence Inspector Rail */}
      <DiagnosticInspectorRail
        snapshot={snapshot}
        currentStage={currentStage}
        maxUnlockedStage={maxUnlockedStage}
        uiMode={uiMode}
        timeline={timeline}
        onRetryFromError={onRetryFromError}
        onRestoreNormalMode={onRestoreNormalMode}
        onOpenFullDiagnosis={onOpenFullDiagnosis}
        compactMode={true}
      />
    </div>
  );
};
