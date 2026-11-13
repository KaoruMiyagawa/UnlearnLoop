import React, { useState } from 'react';
import { DiagnosticInspectorRail } from '../design-system/DiagnosticInspectorRail';
import {
  DecisionTimelineItemView,
  INITIAL_LOOP_STAGE_SNAPSHOTS,
  LoopStageId,
  LoopStageSnapshot,
  TransferInteractiveRecord,
  UiSimulationMode,
} from '../design-system/stage5WorkbenchModel';

interface ReviewWorkspacePlaceholderProps {
  snapshot?: LoopStageSnapshot;
  currentStage?: LoopStageId;
  maxUnlockedStage?: LoopStageId;
  uiMode?: UiSimulationMode;
  timeline?: DecisionTimelineItemView[];
  onRetryFromError?: () => void;
  onRestoreNormalMode?: () => void;
  onSyncStageFromTransfer?: (targetStage: LoopStageId) => void;
  onOpenProgressView?: () => void;
}

const INITIAL_TRANSFER_HISTORY: TransferInteractiveRecord[] = [
  {
    attemptNumber: 1,
    questionId: 'q_py_loop_transfer_01',
    questionTitle: '迁移题 #1 · 仓库双变量步长盘点',
    submittedAnswer: '3 15',
    isCorrect: false,
    sameQuestionRetryBlocked: false,
    outcomeCode: 'transfer_failed_needs_practice',
    resultingKnowledgeStatus: 'needs_practice',
    explanation:
      '首次作答将 running_sum 算成 15（漏加初始值或步长偏差）。保持 needs_practice 并自动生成间隔复习项 ReviewItem (#rev_loop_01)。',
    timestamp: '16:18:10',
  },
];

export const ReviewWorkspacePlaceholder: React.FC<
  ReviewWorkspacePlaceholderProps
> = ({
  snapshot,
  currentStage = 5,
  maxUnlockedStage = 5,
  uiMode = 'normal',
  timeline = [],
  onRetryFromError = () => {},
  onRestoreNormalMode = () => {},
  onSyncStageFromTransfer,
  onOpenProgressView,
}) => {
  const [activeTransferQuestion, setActiveTransferQuestion] = useState<
    'q_py_loop_transfer_01' | 'q_py_loop_transfer_02'
  >('q_py_loop_transfer_01');
  const [transferInput, setTransferInput] = useState('3 17');
  const [transferHistory, setTransferHistory] = useState<TransferInteractiveRecord[]>(
    INITIAL_TRANSFER_HISTORY,
  );
  const [exhaustedPoolSimulated, setExhaustedPoolSimulated] = useState(false);
  const [bannerMessage, setBannerMessage] = useState<{
    tone: 'amber' | 'green' | 'red';
    title: string;
    detail: string;
  } | null>({
    tone: 'amber',
    title: '检测到迁移题 #1 (q_py_loop_transfer_01) 存在历史失败记录 #att_04',
    detail:
      '你可以尝试对同一道题再次提交正确答案 "3 17" 观察防刷分拦截，或者点击“派发全新未作答迁移题 #2”合法验证掌握。',
  });

  const activeSnapshot = snapshot ?? INITIAL_LOOP_STAGE_SNAPSHOTS[currentStage];

  const handleSubmitTransferAttempt = () => {
    const trimmed = transferInput.trim();
    if (!trimmed) return;

    if (activeTransferQuestion === 'q_py_loop_transfer_01') {
      const isAnswerTextRight = trimmed.startsWith('3 17');
      const hasPriorAttemptOnQ1 = transferHistory.some(
        (rec) => rec.questionId === 'q_py_loop_transfer_01',
      );

      if (isAnswerTextRight && hasPriorAttemptOnQ1) {
        const nextRecord: TransferInteractiveRecord = {
          attemptNumber: transferHistory.length + 1,
          questionId: 'q_py_loop_transfer_01',
          questionTitle: '迁移题 #1 · 仓库双变量步长盘点 (同题重答)',
          submittedAnswer: trimmed,
          isCorrect: true,
          sameQuestionRetryBlocked: true,
          outcomeCode: 'transfer_retry_blocked',
          resultingKnowledgeStatus: 'needs_practice',
          explanation:
            '🚫 transfer_retry_blocked：虽然答案 "3 17" 正确，但同一道迁移题 q_py_loop_transfer_01 在当前会话已有历史作答记录。同题重答不能排除记忆答案或试错，拒绝晋升 stable！',
          timestamp: new Date().toTimeString().slice(0, 8),
        };
        setTransferHistory((prev) => [...prev, nextRecord]);
        setBannerMessage({
          tone: 'amber',
          title: '🚫 同题重试防刷分拦截生效 (transfer_retry_blocked)',
          detail:
            '系统识别到 q_py_loop_transfer_01 已存在失败记录。KnowledgeState 保持为 needs_practice (topic_mastered=false)。请点击“派发全新未作答迁移题 #2 (POST /api/v1/sessions/{id}/transfer-check)”获取新情境题！',
        });
        if (onSyncStageFromTransfer) onSyncStageFromTransfer(5);
      } else {
        const nextRecord: TransferInteractiveRecord = {
          attemptNumber: transferHistory.length + 1,
          questionId: 'q_py_loop_transfer_01',
          questionTitle: '迁移题 #1 · 仓库双变量步长盘点',
          submittedAnswer: trimmed,
          isCorrect: false,
          sameQuestionRetryBlocked: false,
          outcomeCode: 'transfer_failed_needs_practice',
          resultingKnowledgeStatus: 'needs_practice',
          explanation:
            '迁移验证作答未通过规则校核，保持 needs_practice 并维持间隔复习计划 ReviewItem。',
          timestamp: new Date().toTimeString().slice(0, 8),
        };
        setTransferHistory((prev) => [...prev, nextRecord]);
        setBannerMessage({
          tone: 'red',
          title: '✕ 迁移验证未通过 · 已记录间隔复习任务 (needs_practice)',
          detail: '同题已被标记为历史已尝试题目，后续需派发新迁移题才能晋升 stable。',
        });
      }
      return;
    }

    // Fresh question q_py_loop_transfer_02
    const isQ2Correct = trimmed.startsWith('3 60');
    if (isQ2Correct) {
      const nextRecord: TransferInteractiveRecord = {
        attemptNumber: transferHistory.length + 1,
        questionId: 'q_py_loop_transfer_02',
        questionTitle: '独立新迁移题 #2 · 温控传感器采样累加 (首次独立作答)',
        submittedAnswer: trimmed,
        isCorrect: true,
        sameQuestionRetryBlocked: false,
        outcomeCode: 'mastery_achieved',
        resultingKnowledgeStatus: 'stable',
        explanation:
          '✓ mastery_achieved：在从未接触过的新情境题 q_py_loop_transfer_02 上首次独立作答正确！满足完整证据链，KnowledgeState 合法更新为 stable（操作性掌握）。',
        timestamp: new Date().toTimeString().slice(0, 8),
      };
      setTransferHistory((prev) => [...prev, nextRecord]);
      setBannerMessage({
        tone: 'green',
        title: '✓ 独立新情境迁移验证首次通过 · 合法晋升 stable (操作性掌握)',
        detail:
          'q_py_loop_transfer_02 无任何历史失败记录，首次作答即准确计算 alerts=3, energy=60。闭环第 6 步已解锁！',
      });
      if (onSyncStageFromTransfer) onSyncStageFromTransfer(6);
    } else {
      const nextRecord: TransferInteractiveRecord = {
        attemptNumber: transferHistory.length + 1,
        questionId: 'q_py_loop_transfer_02',
        questionTitle: '独立新迁移题 #2 · 温控传感器采样累加',
        submittedAnswer: trimmed,
        isCorrect: false,
        sameQuestionRetryBlocked: false,
        outcomeCode: 'transfer_failed_needs_practice',
        resultingKnowledgeStatus: 'needs_practice',
        explanation:
          '新迁移题作答不正确（提示：tick 依次取 2, 4, 6 共 3 轮，energy 初始 24 加上 6+12+18 得 60）。',
        timestamp: new Date().toTimeString().slice(0, 8),
      };
      setTransferHistory((prev) => [...prev, nextRecord]);
      setBannerMessage({
        tone: 'red',
        title: '✕ 新迁移题作答有误 · 提示：可使用快捷填入 "3 60" 演示首次通过',
        detail: '请检查 range(2, 8, 2) 的三轮 tick 值 (2, 4, 6) 与 energy 累加过程。',
      });
    }
  };

  const handleDispatchFreshTransferQuestion = () => {
    setExhaustedPoolSimulated(false);
    setActiveTransferQuestion('q_py_loop_transfer_02');
    setTransferInput('3 60（tick 依次取 2, 4, 6 共 3 轮；energy = 24 + 6 + 12 + 18 = 60）');
    setBannerMessage({
      tone: 'green',
      title: '已派发从未作答过的独立新迁移题 #2 (q_py_loop_transfer_02)',
      detail:
        '[Mock 流程演示] 对应后端正式接口 POST /api/v1/sessions/{id}/transfer-check，自动排除当前会话已尝试过的 q_py_loop_transfer_01 并选取全新情境迁移题。',
    });
  };

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
            ANTI-MEMORIZATION TRANSFER VERIFICATION · 变式迁移验证室
          </div>
          <h1 style={{ margin: '2px 0 4px', fontSize: 22, fontWeight: 700 }}>
            变式迁移验证与防刷分守卫（同题重试拦截 vs 独立新题晋升）
          </h1>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: 13.5 }}>
            直观验证 Stage 3/4 核心领域规则：同题重复答对绝不能直接晋升 <code>stable</code>，必须通过未接触过的独立新迁移题首次答对。
          </p>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="wb-btn sm"
            onClick={() => {
              setActiveTransferQuestion('q_py_loop_transfer_01');
              setTransferInput('3 17');
              setExhaustedPoolSimulated(false);
              if (onSyncStageFromTransfer) onSyncStageFromTransfer(5);
            }}
          >
            切回迁移题 #1 (测试同题拦截)
          </button>
          <button
            type="button"
            className="wb-btn primary sm"
            onClick={handleDispatchFreshTransferQuestion}
          >
            派发独立新迁移题 #2 (q_py_loop_transfer_02) →
          </button>
          <button
            type="button"
            className={`wb-btn sm ${exhaustedPoolSimulated ? 'danger' : ''}`}
            onClick={() => setExhaustedPoolSimulated((prev) => !prev)}
          >
            {exhaustedPoolSimulated ? '关闭题池耗尽降级演示' : '模拟新迁移题池耗尽 (409 降级保护)'}
          </button>
        </div>
      </div>

      <div className="wb-grid">
        {/* Left Interactive Transfer Lab Column */}
        <div>
          {/* Three-Stage Visual Comparison Banner */}
          <section className="wb-card" aria-labelledby="transfer-three-stage-heading">
            <div className="wb-card-head">
              <h2 id="transfer-three-stage-heading" className="wb-card-title">
                三阶段迁移验证防伪造掌握流程对比
              </h2>
              <span className="wb-badge purple">
                stable = 当前阶段操作性掌握（非永久绝对掌握）
              </span>
            </div>

            <div className="wb-card-body" style={{ display: 'grid', gap: 12 }}>
              <div
                style={{
                  padding: '13px 15px',
                  border: '1px solid #FECDD3',
                  background: 'var(--danger-soft)',
                  borderRadius: 8,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <strong>
                    阶段 A：迁移题 #1 (<code>q_py_loop_transfer_01</code>) 首次作答失败
                  </strong>
                  <span className="wb-badge red">needs_practice + ReviewItem</span>
                </div>
                <p style={{ margin: '5px 0 0', fontSize: 12.5 }}>
                  学习者首次提交 <code>"3 15"</code>（累加错误）。系统保持{' '}
                  <code>needs_practice</code> 并自动创建间隔复习计划 <code>ReviewItem</code>，同时将该题标记为“本会话已尝试”。
                </p>
              </div>

              <div
                style={{
                  padding: '13px 15px',
                  border: '1px solid #FDE68A',
                  background: 'var(--warning-soft)',
                  borderRadius: 8,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <strong>
                    阶段 B：对同一道迁移题 #1 重试提交正确答案 <code>"3 17"</code>
                  </strong>
                  <span className="wb-badge amber">🚫 transfer_retry_blocked</span>
                </div>
                <p style={{ margin: '5px 0 0', fontSize: 12.5 }}>
                  <strong>核心防刷分守卫：</strong>虽然第 2 次提交的 <code>"3 17"</code> 文本正确，但系统检索到该题存在同会话历史失败记录。同题重答无法排除背答案或穷举试错，<strong>拒绝晋升 <code>stable</code></strong>！
                </p>
              </div>

              <div
                style={{
                  padding: '13px 15px',
                  border: '1px solid #A7F3D0',
                  background: 'var(--success-soft)',
                  borderRadius: 8,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <strong>
                    阶段 C：派发全新未作答迁移题 #2 (<code>q_py_loop_transfer_02</code>) 首次答对 <code>"3 60"</code>
                  </strong>
                  <span className="wb-badge green">✓ mastery_achieved (stable)</span>
                </div>
                <p style={{ margin: '5px 0 0', fontSize: 12.5 }}>
                  表面情境切换为“温控传感器采样”，底层仍考查同一目标概念 <code>py-for-loop</code>。在无历史失败污染的新题上首次独立作答正确，合法晋升为 <code>stable</code>。
                </p>
              </div>
            </div>
          </section>

          {/* Interactive Transfer Sandbox */}
          <section className="wb-card" aria-labelledby="transfer-sandbox-heading">
            <div className="wb-card-head">
              <div>
                <h2 id="transfer-sandbox-heading" className="wb-card-title">
                  交互式迁移验证演练台（当前题目：<code>{activeTransferQuestion}</code>）
                </h2>
              </div>
              <span
                className={`wb-badge ${
                  activeTransferQuestion === 'q_py_loop_transfer_01' ? 'amber' : 'green'
                }`}
              >
                {activeTransferQuestion === 'q_py_loop_transfer_01'
                  ? '已被首次失败污染 · 同题重答将触发拦截'
                  : '全新未尝试题目 · 首次答对可晋升 stable'}
              </span>
            </div>

            <div className="wb-card-body">
              {exhaustedPoolSimulated && (
                <div
                  role="alert"
                  style={{
                    padding: '12px 14px',
                    marginBottom: 14,
                    borderRadius: 8,
                    background: 'var(--warning-soft)',
                    border: '1px solid #FDE68A',
                    color: 'var(--warning)',
                    fontSize: 13,
                  }}
                >
                  <strong>
                    ⚠️ 新迁移题池耗尽保守降级 (<code>fresh_transfer_pool_exhausted</code>)：
                  </strong>{' '}
                  当内容包中没有更多未尝试过的 <code>transfer_check</code> 题目时，系统返回明确降级状态（保持{' '}
                  <code>needs_practice</code> 并安排后续间隔复习），绝不降级允许旧题重答冒充 <code>stable</code>！
                </div>
              )}

              {bannerMessage && (
                <div
                  role="status"
                  style={{
                    padding: '12px 14px',
                    marginBottom: 14,
                    borderRadius: 8,
                    background:
                      bannerMessage.tone === 'green'
                        ? 'var(--success-soft)'
                        : bannerMessage.tone === 'amber'
                          ? 'var(--warning-soft)'
                          : 'var(--danger-soft)',
                    border:
                      bannerMessage.tone === 'green'
                        ? '1px solid #A7F3D0'
                        : bannerMessage.tone === 'amber'
                          ? '1px solid #FDE68A'
                          : '1px solid #FECDD3',
                    fontSize: 13,
                  }}
                >
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>{bannerMessage.title}</div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>
                    {bannerMessage.detail}
                  </div>
                </div>
              )}

              {activeTransferQuestion === 'q_py_loop_transfer_01' ? (
                <>
                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>
                    【迁移题 #1 · 仓库双变量盘点】预测下方代码最终打印的 <code>count</code> 与{' '}
                    <code>running_sum</code>：
                  </div>
                  <div className="wb-code-box">
                    <div className="wb-code-head">
                      <span>python3 · q_py_loop_transfer_01 (本会话已有失败记录 #att_04)</span>
                      <span>role: transfer_check</span>
                    </div>
                    <pre>{`count = 0\nrunning_sum = 5\nfor step in range(1, 7, 2):\n    count += 1\n    running_sum += step * 2\nprint(count, running_sum)`}</pre>
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                    <button
                      type="button"
                      className="wb-btn sm"
                      onClick={() => setTransferInput('3 17')}
                    >
                      填入同题重答正确答案 "3 17" (触发防刷分拦截)
                    </button>
                    <button
                      type="button"
                      className="wb-btn sm"
                      onClick={() => setTransferInput('3 15')}
                    >
                      填入错误答案 "3 15"
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>
                    【独立新迁移题 #2 · 温控传感器采样累加】预测下方代码最终打印的{' '}
                    <code>alerts</code> 与 <code>energy</code>：
                  </div>
                  <div className="wb-code-box">
                    <div className="wb-code-head">
                      <span>python3 · q_py_loop_transfer_02 (本会话从未尝试过的全新迁移题)</span>
                      <span>role: transfer_check</span>
                    </div>
                    <pre>{`alerts = 0\nenergy = 24\nfor tick in range(2, 8, 2):\n    alerts += 1\n    energy += tick * 3\nprint(alerts, energy)`}</pre>
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                    <button
                      type="button"
                      className="wb-btn sm"
                      onClick={() =>
                        setTransferInput(
                          '3 60（tick 依次取 2, 4, 6 共 3 轮；energy = 24 + 6 + 12 + 18 = 60）',
                        )
                      }
                    >
                      填入首次独立正确作答 "3 60" (合法晋升 stable)
                    </button>
                  </div>
                </>
              )}

              <textarea
                className="wb-textarea"
                style={{ minHeight: 78 }}
                value={transferInput}
                onChange={(e) => setTransferInput(e.target.value)}
              />

              <div className="wb-btn-group">
                <button
                  type="button"
                  className="wb-btn primary"
                  onClick={handleSubmitTransferAttempt}
                >
                  {activeTransferQuestion === 'q_py_loop_transfer_01'
                    ? '提交迁移题 #1 作答并验证防刷分守卫'
                    : '提交独立新迁移题 #2 作答并验证 stable 晋升'}
                </button>

                {activeTransferQuestion === 'q_py_loop_transfer_01' && (
                  <button
                    type="button"
                    className="wb-btn"
                    onClick={handleDispatchFreshTransferQuestion}
                  >
                    派发未作答过的独立新迁移题 #2 (POST /api/v1/sessions/:id/transfer-check) →
                  </button>
                )}

                {onOpenProgressView && (
                  <button type="button" className="wb-btn" onClick={onOpenProgressView}>
                    查看掌握度档案与复习计划 →
                  </button>
                )}
              </div>

              {/* Attempt History Log for Transfer Verification */}
              <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--border-default)' }}>
                <strong style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>
                  当前会话迁移验证提交审计记录 ({transferHistory.length} 次)：
                </strong>
                <div style={{ display: 'grid', gap: 8 }}>
                  {transferHistory.map((item) => (
                    <div
                      key={`${item.attemptNumber}-${item.timestamp}`}
                      style={{
                        padding: '10px 12px',
                        borderRadius: 8,
                        background: 'var(--surface-page)',
                        border: '1px solid var(--border-default)',
                        fontSize: 12.5,
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
                        <span>
                          <strong>第 {item.attemptNumber} 次迁移提交</strong> ·{' '}
                          <code>{item.questionId}</code> · 输入：<code>"{item.submittedAnswer}"</code>
                        </span>
                        <span
                          className={`wb-badge ${
                            item.outcomeCode === 'mastery_achieved'
                              ? 'green'
                              : item.outcomeCode === 'transfer_retry_blocked'
                                ? 'amber'
                                : 'red'
                          }`}
                        >
                          {item.outcomeCode} → {item.resultingKnowledgeStatus}
                        </span>
                      </div>
                      <div style={{ marginTop: 4, color: 'var(--text-secondary)' }}>
                        {item.explanation}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
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
          compactMode={true}
        />
      </div>
    </div>
  );
};
