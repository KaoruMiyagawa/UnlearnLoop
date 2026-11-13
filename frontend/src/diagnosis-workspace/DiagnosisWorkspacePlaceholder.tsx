import React, { useState } from 'react';
import { DiagnosticInspectorRail } from '../design-system/DiagnosticInspectorRail';
import {
  DecisionTimelineItemView,
  INITIAL_LOOP_STAGE_SNAPSHOTS,
  LoopStageId,
  LoopStageSnapshot,
  UiSimulationMode,
} from '../design-system/stage5WorkbenchModel';

interface DiagnosisWorkspacePlaceholderProps {
  snapshot?: LoopStageSnapshot;
  currentStage?: LoopStageId;
  maxUnlockedStage?: LoopStageId;
  uiMode?: UiSimulationMode;
  timeline?: DecisionTimelineItemView[];
  onRetryFromError?: () => void;
  onRestoreNormalMode?: () => void;
  onAdvanceStage?: () => void;
  onReturnToLearning?: () => void;
}

const WHITELISTED_AGENT_TOOLS = [
  {
    toolName: 'select_diagnostic_followup',
    stageUsed: 'Stage 2',
    purpose: '从内容包预置追问池中选择信息区分度最高的问题，并列裁决 H1 与 H2，禁止自由编造离题追问。',
  },
  {
    toolName: 'provide_targeted_explanation',
    stageUsed: 'Stage 3',
    purpose: '针对已确认的错误假设（如 range_start_at_one）提供结构化概念纠偏，不直接泄露后续练习题答案。',
  },
  {
    toolName: 'assign_targeted_practice',
    stageUsed: 'Stage 3 → 4',
    purpose: '派发与已确认假设绑定的针对性边界练习题，验证纠偏是否缓解该假设。',
  },
  {
    toolName: 'assign_transfer_verification',
    stageUsed: 'Stage 4 → 5/6',
    purpose: '强制要求跨表面结构的独立变式题验证；拦截同题重复答对直接晋升 stable。',
  },
  {
    toolName: 'update_knowledge_state / schedule_spaced_review',
    stageUsed: 'Stage 5 / 6',
    purpose: '依据完整证据链更新 KnowledgeState（stable / needs_practice）并生成间隔复习计划 ReviewItem。',
  },
] as const;

export const DiagnosisWorkspacePlaceholder: React.FC<
  DiagnosisWorkspacePlaceholderProps
> = ({
  snapshot,
  currentStage = 2,
  maxUnlockedStage = 2,
  uiMode = 'normal',
  timeline = [],
  onRetryFromError = () => {},
  onRestoreNormalMode = () => {},
  onAdvanceStage,
  onReturnToLearning,
}) => {
  const [degradedPreview, setDegradedPreview] = useState(false);

  const activeSnapshot = snapshot ?? INITIAL_LOOP_STAGE_SNAPSHOTS[currentStage];
  const visibleTimeline = timeline.filter(
    (item) => item.stageReachableAt <= maxUnlockedStage,
  );

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
            AGENT DIAGNOSTIC & EVIDENCE INSPECTOR · 方案 B 核心视图
          </div>
          <h1 style={{ margin: '2px 0 4px', fontSize: 22, fontWeight: 700 }}>
            Agent 诊断检视器与竞争性错误假设矩阵
          </h1>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: 13.5 }}>
            动态展示当前阶段（第 {currentStage} / 6 步）的学习者原始作答快照、多个竞争性错误假设、正反证据链与受控工具决策解释。
          </p>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={() => setDegradedPreview((prev) => !prev)}
            className={`wb-btn sm ${degradedPreview ? 'primary' : ''}`}
          >
            {degradedPreview
              ? '✓ 已开启规则降级模式预览 (degraded_mode=true)'
              : '预览远程模型不可用降级态 (degraded_mode)'}
          </button>
          {onReturnToLearning && (
            <button type="button" onClick={onReturnToLearning} className="wb-btn sm">
              ← 返回双栏学习工作台作答
            </button>
          )}
        </div>
      </div>

      {degradedPreview && (
        <div
          role="status"
          style={{
            padding: '12px 16px',
            marginBottom: 18,
            borderRadius: 10,
            background: 'var(--warning-soft)',
            border: '1px solid #FDE68A',
            color: 'var(--warning)',
            fontSize: 13,
          }}
        >
          <strong>⚡ 确定性规则降级模式已激活 (<code>degraded_mode = true</code>)：</strong>{' '}
          当远程 LLM 超时、Token 预算耗尽或离线时，系统自动由确定性 <code>RuleEvaluator</code> 接管诊断决策，优先派发低成本追问或保守标记{' '}
          <code>insufficient_evidence</code>，绝不伪造高置信度掌握结论。
        </div>
      )}

      <div className="wb-grid">
        {/* Left Deep-Dive Evidence & Hypothesis Evolution Column */}
        <div>
          {/* 1. Stage-Driven Hypothesis Comparison Matrix */}
          <section className="wb-card" aria-labelledby="diag-matrix-heading">
            <div className="wb-card-head">
              <div>
                <h2 id="diag-matrix-heading" className="wb-card-title">
                  跨阶段竞争假设权重演化对比（第 1 步 → 当前已解锁第 {maxUnlockedStage} 步）
                </h2>
              </div>
              <span className="wb-badge slate">
                启发式工作判断 · 非校准统计概率 (<code>confidence_is_heuristic=true</code>)
              </span>
            </div>

            <div className="wb-card-body">
              <div style={{ overflowX: 'auto' }}>
                <table
                  style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: 12.5,
                    textAlign: 'left',
                  }}
                >
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-default)', color: 'var(--text-muted)' }}>
                      <th style={{ padding: '8px 10px' }}>候选错误假设</th>
                      <th style={{ padding: '8px 10px' }}>Step 1-2 (初答后)</th>
                      <th style={{ padding: '8px 10px' }}>Step 3 (追问后)</th>
                      <th style={{ padding: '8px 10px' }}>Step 4-5 (练习/同题拦截)</th>
                      <th style={{ padding: '8px 10px' }}>Step 6 (新迁移题通过)</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr style={{ borderBottom: '1px solid var(--border-default)' }}>
                      <td style={{ padding: '10px' }}>
                        <strong>
                          <code>H1: range_start_at_one</code>
                        </strong>
                        <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                          误以为 range(3) 从 1 开始
                        </div>
                      </td>
                      <td style={{ padding: '10px' }}>
                        <span className="wb-badge amber">38% · candidate</span>
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 3 ? (
                          <span className="wb-badge red">86% · confirmed</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待追问解锁</span>
                        )}
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 4 ? (
                          <span className="wb-badge blue">35% · lowered</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待练习解锁</span>
                        )}
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 6 ? (
                          <span className="wb-badge green">10% · resolved</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待新题验证</span>
                        )}
                      </td>
                    </tr>

                    <tr style={{ borderBottom: '1px solid var(--border-default)' }}>
                      <td style={{ padding: '10px' }}>
                        <strong>
                          <code>H2: loop_memorized_without_trace</code>
                        </strong>
                        <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                          仅记忆答案无逐轮状态追踪
                        </div>
                      </td>
                      <td style={{ padding: '10px' }}>
                        <span className="wb-badge amber">48% · insufficient_ev</span>
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 3 ? (
                          <span className="wb-badge slate">12% · 反驳下调</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待追问解锁</span>
                        )}
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 5 ? (
                          <span className="wb-badge amber">24% · 同题重试预警</span>
                        ) : maxUnlockedStage >= 4 ? (
                          <span className="wb-badge slate">12% · lowered</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待练习解锁</span>
                        )}
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 6 ? (
                          <span className="wb-badge green">8% · resolved</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待新题验证</span>
                        )}
                      </td>
                    </tr>

                    <tr>
                      <td style={{ padding: '10px' }}>
                        <strong>
                          <code>H3: range_stop_inclusive</code>
                        </strong>
                        <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                          误以为 range(3) 包含上界 3
                        </div>
                      </td>
                      <td style={{ padding: '10px' }}>
                        <span className="wb-badge slate">14% · 初答反驳</span>
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 3 ? (
                          <span className="wb-badge slate">8% · 已排除</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待追问解锁</span>
                        )}
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 4 ? (
                          <span className="wb-badge slate">&lt;5% · 已排除</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待练习解锁</span>
                        )}
                      </td>
                      <td style={{ padding: '10px' }}>
                        {maxUnlockedStage >= 6 ? (
                          <span className="wb-badge green">已排除</span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>🔒 待新题验证</span>
                        )}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {onAdvanceStage && currentStage < 6 && (
                <div className="wb-btn-group" style={{ marginTop: 16 }}>
                  <button type="button" className="wb-btn primary" onClick={onAdvanceStage}>
                    执行当前阶段诊断动作并推进至第 {currentStage + 1} 步 →
                  </button>
                </div>
              )}
            </div>
          </section>

          {/* 2. Whitelisted Tool Registry & Anti-Hallucination Contract */}
          <section className="wb-card" aria-labelledby="tool-whitelist-heading">
            <div className="wb-card-head">
              <h2 id="tool-whitelist-heading" className="wb-card-title">
                DiagnosticAgentEngine 受控工具白名单与防越权机制
              </h2>
              <span className="wb-badge blue">拒绝自由文本直接篡改掌握度</span>
            </div>
            <div className="wb-card-body" style={{ display: 'grid', gap: 10 }}>
              {WHITELISTED_AGENT_TOOLS.map((tool) => {
                const isActiveTool = activeSnapshot.agentToolName.includes(tool.toolName);
                return (
                  <div
                    key={tool.toolName}
                    style={{
                      padding: '10px 14px',
                      borderRadius: 8,
                      border: isActiveTool
                        ? '1px solid var(--action-primary)'
                        : '1px solid var(--border-default)',
                      background: isActiveTool ? 'var(--action-soft)' : 'var(--surface-page)',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'flex-start',
                      gap: 12,
                      flexWrap: 'wrap',
                    }}
                  >
                    <div>
                      <div>
                        <code>
                          <strong>{tool.toolName}</strong>
                        </code>{' '}
                        <span className="wb-badge slate" style={{ marginLeft: 6 }}>
                          {tool.stageUsed}
                        </span>
                        {isActiveTool && (
                          <span className="wb-badge blue" style={{ marginLeft: 6 }}>
                            ● 当前阶段选中工具
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 4 }}>
                        {tool.purpose}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* 3. Full DecisionEvent Audit Log */}
          <section className="wb-card" aria-labelledby="full-audit-heading">
            <div className="wb-card-head">
              <h2 id="full-audit-heading" className="wb-card-title">
                可回放诊断决策事件流 (DecisionEvent Audit Trail)
              </h2>
              <span className="wb-badge slate">
                已生成 {visibleTimeline.length} 条记录
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
                    gap: 10,
                    flexWrap: 'wrap',
                    paddingBottom: 8,
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

        {/* Right Live Agent Diagnostic & Evidence Inspector */}
        <DiagnosticInspectorRail
          snapshot={activeSnapshot}
          currentStage={currentStage}
          maxUnlockedStage={maxUnlockedStage}
          uiMode={uiMode}
          timeline={timeline}
          onRetryFromError={onRetryFromError}
          onRestoreNormalMode={onRestoreNormalMode}
          compactMode={false}
        />
      </div>
    </div>
  );
};
