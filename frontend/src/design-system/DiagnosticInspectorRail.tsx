import React from 'react';
import {
  DecisionTimelineItemView,
  LoopStageId,
  LoopStageSnapshot,
  UiSimulationMode,
} from './stage5WorkbenchModel';

interface DiagnosticInspectorRailProps {
  snapshot: LoopStageSnapshot;
  currentStage: LoopStageId;
  maxUnlockedStage: LoopStageId;
  uiMode: UiSimulationMode;
  timeline: DecisionTimelineItemView[];
  onRetryFromError: () => void;
  onRestoreNormalMode: () => void;
  onOpenFullDiagnosis?: () => void;
  compactMode?: boolean;
}

export const DiagnosticInspectorRail: React.FC<DiagnosticInspectorRailProps> = ({
  snapshot,
  currentStage,
  maxUnlockedStage,
  uiMode,
  timeline,
  onRetryFromError,
  onRestoreNormalMode,
  onOpenFullDiagnosis,
  compactMode = true,
}) => {
  const visibleTimeline = timeline.filter(
    (item) => item.stageReachableAt <= maxUnlockedStage,
  );

  if (uiMode === 'loading') {
    return (
      <aside aria-label="Agent 诊断检视器加载中">
        <div className="wb-card">
          <div className="wb-card-head">
            <h3 className="wb-card-title">实时 Agent 诊断与证据检视器</h3>
            <span className="wb-badge blue">模型推理与证据同步中…</span>
          </div>
          <div className="wb-card-body">
            <div className="wb-skeleton" style={{ height: 18, width: '55%', marginBottom: 10 }} />
            <div className="wb-skeleton" style={{ height: 48, width: '100%', marginBottom: 16 }} />
            <div className="wb-skeleton" style={{ height: 18, width: '65%', marginBottom: 10 }} />
            <div className="wb-skeleton" style={{ height: 112, width: '100%', marginBottom: 12 }} />
            <div className="wb-skeleton" style={{ height: 96, width: '100%', marginBottom: 12 }} />
            <div className="wb-skeleton" style={{ height: 68, width: '100%' }} />
          </div>
        </div>
      </aside>
    );
  }

  if (uiMode === 'empty') {
    return (
      <aside aria-label="Agent 诊断检视器空状态">
        <div className="wb-card">
          <div className="wb-card-head">
            <h3 className="wb-card-title">实时 Agent 诊断与证据检视器</h3>
            <span className="wb-badge slate">INSUFFICIENT_EVIDENCE · 暂无快照</span>
          </div>
          <div className="wb-card-body">
            <div
              style={{
                padding: '16px',
                borderRadius: 8,
                border: '1px dashed var(--border-strong)',
                background: 'var(--surface-page)',
              }}
            >
              <strong style={{ display: 'block', fontSize: 13.5, marginBottom: 6 }}>
                尚未采集到当前会话的原始作答证据
              </strong>
              <p style={{ margin: 0, fontSize: 12.5, color: 'var(--text-secondary)' }}>
                UnlearnLoop 拒绝在没有任何证据时预判学习者错误原因。请先在左侧学习工作区提交第 1 步初始作答，或恢复默认交互演示状态。
              </p>
              <div className="wb-btn-group">
                <button type="button" className="wb-btn primary sm" onClick={onRestoreNormalMode}>
                  恢复默认诊断证据流 →
                </button>
              </div>
            </div>
          </div>
        </div>
      </aside>
    );
  }

  return (
    <aside aria-label="实时 Agent 诊断与证据检视器">
      <div className="wb-card">
        <div className="wb-card-head">
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--action-primary)' }}>
              STAGE {currentStage} / 6 · LIVE INSPECTOR (MOCK)
            </div>
            <h3 className="wb-card-title">实时 Agent 诊断与证据检视器</h3>
          </div>
          <span className={`wb-badge ${uiMode === 'error' ? 'red' : snapshot.uncertaintyTone}`}>
            {uiMode === 'error' ? 'RETRY_WAITING（待重试恢复）' : snapshot.uncertaintyLabel}
          </span>
        </div>

        <div className="wb-card-body">
          {/* Error / Retry Recovery Banner */}
          {uiMode === 'error' && (
            <div
              role="alert"
              style={{
                padding: '12px 14px',
                marginBottom: 16,
                borderRadius: 8,
                background: 'var(--danger-soft)',
                border: '1px solid #FECDD3',
                color: 'var(--danger)',
                fontSize: 12.5,
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: 4 }}>
                ⚠️ 诊断单步调用超时 · 会话已安全保护为 <code>retry_waiting</code>
              </div>
              <p style={{ margin: 0, color: 'var(--text-primary)' }}>
                学习者原始作答快照 <code>#{snapshot.rawAttemptId}</code> 与本地草稿已完整保留，未产生半提交脏状态。可点击下方按钮从挂起断点安全重试，或切换为规则降级模式（<code>degraded_mode=true</code>）。
              </p>
              <div className="wb-btn-group" style={{ marginTop: 10 }}>
                <button type="button" className="wb-btn primary sm" onClick={onRetryFromError}>
                  从 retry_waiting 断点重试诊断 Step →
                </button>
              </div>
            </div>
          )}

          {/* 1. Learner Immutable Raw Attempt Snapshot */}
          <div style={{ marginBottom: 16 }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                fontSize: 12,
                color: 'var(--text-muted)',
                marginBottom: 5,
              }}
            >
              <span>学习者原始作答不可变快照 (Immutable Attempt)</span>
              <code>
                #{snapshot.rawAttemptId} · {snapshot.rawAttemptTimestamp}
              </code>
            </div>
            <div
              style={{
                padding: '10px 12px',
                background: 'var(--surface-page)',
                border: '1px solid var(--border-default)',
                borderRadius: 8,
                fontFamily: 'var(--font-mono)',
                fontSize: 12.5,
              }}
            >
              <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                提交内容："{snapshot.rawAttemptText}"
              </div>
              <div
                style={{
                  marginTop: 4,
                  fontSize: 12,
                  fontFamily: 'var(--font-sans)',
                  color: 'var(--text-secondary)',
                }}
              >
                {snapshot.rawAttemptNote}
              </div>
            </div>
          </div>

          {/* 2. Competing Error Hypotheses + Mandatory Heuristic Disclaimer */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 8,
              flexWrap: 'wrap',
              marginBottom: 8,
            }}
          >
            <strong style={{ fontSize: 13 }}>
              并列竞争性错误假设 ({snapshot.hypotheses.length} 项)
            </strong>
            <span
              className="wb-badge slate"
              title="confidence_is_heuristic = true：仅用于驱动下一步追问与干预优先级，绝非统计校准概率"
              style={{ fontSize: 11 }}
            >
              启发式工作权重 · 非统计概率 (<code>confidence_is_heuristic=true</code>)
            </span>
          </div>

          {snapshot.hypotheses.map((hyp) => {
            const barColor =
              hyp.heuristicWeightPct >= 65
                ? 'var(--danger)'
                : hyp.heuristicWeightPct >= 30
                  ? 'var(--warning)'
                  : 'var(--success)';

            return (
              <div key={hyp.hypothesisCode} className="wb-hyp-card">
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    gap: 8,
                    fontSize: 13,
                  }}
                >
                  <div>
                    <strong>
                      <code>{hyp.hypothesisCode}</code>
                    </strong>
                    <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 2 }}>
                      {hyp.title}
                    </div>
                  </div>
                  <span className={`wb-badge ${hyp.badgeTone}`}>
                    {hyp.statusLabel} · 启发式权重 {hyp.heuristicWeightPct}%
                  </span>
                </div>

                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                  {hyp.description}
                </div>

                <div className="wb-hyp-bar-track" aria-hidden="true">
                  <div
                    className="wb-hyp-bar-fill"
                    style={{
                      width: `${hyp.heuristicWeightPct}%`,
                      background: barColor,
                    }}
                  />
                </div>

                {/* Supporting, Contradicting, Neutral & Missing Evidence List */}
                <div className="wb-ev-list">
                  {hyp.evidences.map((ev) => {
                    const toneClass =
                      ev.polarity === 'supports'
                        ? 'sup'
                        : ev.polarity === 'contradicts'
                          ? 'con'
                          : ev.polarity === 'missing'
                            ? 'mis'
                            : '';
                    return (
                      <div key={ev.id} className={`wb-ev-entry ${toneClass}`}>
                        <span>
                          <strong>[{ev.polarityLabel}]</strong> {ev.summary}
                        </span>
                        <code style={{ flexShrink: 0, fontSize: 11.5 }}>{ev.sourceRef}</code>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* 3. Next Agent Whitelisted Tool Decision & Explanation */}
          <div
            style={{
              marginTop: 14,
              padding: '13px 14px',
              background: 'var(--action-soft)',
              border: '1px solid #BFDBFE',
              borderRadius: 9,
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
              <span
                style={{
                  fontSize: 11.5,
                  fontWeight: 700,
                  color: 'var(--action-primary)',
                  textTransform: 'uppercase',
                }}
              >
                Agent 下一步受控工具决策 · <code>{snapshot.agentToolName}</code>
              </span>
              <span className="wb-badge blue">白名单工具契约校验通过</span>
            </div>
            <p style={{ margin: '6px 0 0', fontSize: 12.5, color: 'var(--text-primary)' }}>
              {snapshot.agentDecisionReason}
            </p>
            <div
              style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: '1px dashed #BFDBFE',
                fontSize: 12,
                color: 'var(--text-secondary)',
              }}
            >
              <strong>领域状态机约束：</strong>
              {snapshot.agentNextExpectation}
            </div>
          </div>

          {compactMode && onOpenFullDiagnosis && (
            <div className="wb-btn-group" style={{ justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                已解锁决策事件：{visibleTimeline.length} / {timeline.length} 条
              </span>
              <button type="button" className="wb-btn sm" onClick={onOpenFullDiagnosis}>
                在独立诊断检视器中展开全量证据矩阵 →
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};
