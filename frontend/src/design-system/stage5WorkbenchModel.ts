export type LoopStageId = 1 | 2 | 3 | 4 | 5 | 6;

export type UiSimulationMode = 'normal' | 'loading' | 'empty' | 'error';

export type WorkbenchBadgeTone = 'blue' | 'green' | 'amber' | 'red' | 'purple' | 'slate';

export type SessionStatus =
  | 'active'
  | 'diagnosing'
  | 'intervening'
  | 'transfer_checking'
  | 'paused'
  | 'retry_waiting'
  | 'completed';

export type KnowledgeMasteryStatus =
  | 'insufficient_evidence'
  | 'needs_diagnosis'
  | 'needs_practice'
  | 'stable';

export type QuestionRole =
  | 'initial'
  | 'diagnostic_followup'
  | 'targeted_practice'
  | 'transfer_check';

export interface EvidenceEntryView {
  id: string;
  polarity: 'supports' | 'contradicts' | 'neutral' | 'missing';
  polarityLabel: string;
  summary: string;
  sourceRef: string;
}

export interface CompetingHypothesisView {
  hypothesisCode: string;
  title: string;
  description: string;
  heuristicWeightPct: number;
  confidenceIsHeuristic: true;
  status: 'candidate' | 'insufficient_evidence' | 'confirmed' | 'lowered' | 'resolved';
  statusLabel: string;
  badgeTone: WorkbenchBadgeTone;
  evidences: EvidenceEntryView[];
}

export interface DecisionTimelineItemView {
  eventId: string;
  stageReachableAt: LoopStageId;
  toolName: string;
  summary: string;
  outcomeCode: string;
  badgeTone: WorkbenchBadgeTone;
  timestamp: string;
}

export interface SanitizedTaskCardView {
  questionId: string;
  questionVersion: number;
  questionRole: QuestionRole;
  roleLabel: string;
  promptTitle: string;
  promptDescription: string;
  codeLanguage: string;
  codeSnippet: string;
  defaultDraft: string;
  recommendedInputs: {
    label: string;
    value: string;
    hint: string;
  }[];
  primaryActionLabel: string;
}

export interface LoopStageSnapshot {
  stage: LoopStageId;
  shortLabel: string;
  stageTitle: string;
  sessionStatus: SessionStatus;
  sessionStatusDisplay: string;
  knowledgeStatus: KnowledgeMasteryStatus;
  topicMastered: boolean;
  uncertaintyCode: string;
  uncertaintyLabel: string;
  uncertaintyTone: WorkbenchBadgeTone;
  degradedMode: boolean;
  rawAttemptId: string;
  rawAttemptTimestamp: string;
  rawAttemptText: string;
  rawAttemptNote: string;
  agentToolName: string;
  agentDecisionReason: string;
  agentNextExpectation: string;
  task: SanitizedTaskCardView;
  hypotheses: CompetingHypothesisView[];
}

export interface TransferInteractiveRecord {
  attemptNumber: number;
  questionId: string;
  questionTitle: string;
  submittedAnswer: string;
  isCorrect: boolean;
  sameQuestionRetryBlocked: boolean;
  outcomeCode: 'transfer_failed_needs_practice' | 'transfer_retry_blocked' | 'mastery_achieved';
  resultingKnowledgeStatus: KnowledgeMasteryStatus;
  explanation: string;
  timestamp: string;
}

export interface TopicMasteryMatrixItem {
  topicSlug: string;
  topicTitle: string;
  prerequisiteSlugs: string[];
  sessionStatus: SessionStatus;
  knowledgeStatus: KnowledgeMasteryStatus;
  topicMastered: boolean;
  completionReason: string;
  confidenceScore: number;
  confidenceIsHeuristic: true;
  lastEvidenceSummary: string;
  reviewDueStatus: 'due_now' | 'scheduled' | 'completed' | 'none';
  reviewItemId?: string;
  reviewReason?: string;
}

export const INITIAL_LOOP_STAGE_SNAPSHOTS: Record<LoopStageId, LoopStageSnapshot> = {
  1: {
    stage: 1,
    shortLabel: '1. 初始作答 ("3")',
    stageTitle: '第 1 步：提交初始作答与确定性规则预检 (RuleEvaluator)',
    sessionStatus: 'active',
    sessionStatusDisplay: 'active → diagnosing',
    knowledgeStatus: 'insufficient_evidence',
    topicMastered: false,
    uncertaintyCode: 'INSUFFICIENT_EVIDENCE',
    uncertaintyLabel: 'INSUFFICIENT_EVIDENCE（证据不足）',
    uncertaintyTone: 'amber',
    degradedMode: false,
    rawAttemptId: 'att_01_init',
    rawAttemptTimestamp: '16:10:04',
    rawAttemptText: '3',
    rawAttemptNote: '仅提交最终输出数字 "3"，未提供循环变量 i 与累加器 total 的逐轮状态追踪。',
    agentToolName: 'rule_pre_evaluation (RuleEvaluator)',
    agentDecisionReason:
      '答案 "3" 与表面结果吻合，但缺少执行过程追踪证据。系统拒绝直接判定掌握，自动生成 3 个竞争性候选错误假设（H1: 起始边界误判 1+2=3；H2: 仅背诵结果无追踪；H3: 终止边界包含误判）。',
    agentNextExpectation:
      '提交初始作答后，系统将进入 diagnosing 状态并保存不可变原始作答快照 #att_01_init。',
    task: {
      questionId: 'q_py_loop_initial_01',
      questionVersion: 1,
      questionRole: 'initial',
      roleLabel: 'initial · 初始诊断题 (q_py_loop_initial_01)',
      promptTitle: '阅读下方 Python 循环代码，预测最终打印的值，并说明每轮 i 与 total 的变化：',
      promptDescription:
        '脱敏题目视图（SanitizedQuestionResponse）：前端严格隐去标准答案与内部评分规则，仅暴露当前会话已合法分配的题目内容。',
      codeLanguage: 'python3',
      codeSnippet: `total = 0\nfor i in range(3):\n    total = total + i\nprint(total)`,
      defaultDraft: '3',
      recommendedInputs: [
        {
          label: '填入巧合答案 "3"（无追踪过程）',
          value: '3',
          hint: '触发证据不足与竞争假设并列保留',
        },
        {
          label: '填入错误答案 "6"（误把 3 包含在内）',
          value: '6（误算 1+2+3=6）',
          hint: '触发终止边界包含假设 H3 上升',
        },
      ],
      primaryActionLabel: '提交初始作答并生成竞争性假设 (进入第 2 步) →',
    },
    hypotheses: [
      {
        hypothesisCode: 'H1: range_start_at_one',
        title: '误以为 range(n) 默认从 1 开始而非 0',
        description: '将 range(3) 当作 [1, 2] 两轮累加 (1 + 2 = 3)，与正确过程 (0 + 1 + 2 = 3) 输出碰巧相同。',
        heuristicWeightPct: 38,
        confidenceIsHeuristic: true,
        status: 'candidate',
        statusLabel: 'candidate（并列候选）',
        badgeTone: 'amber',
        evidences: [
          {
            id: 'ev_101',
            polarity: 'neutral',
            polarityLabel: '中立兼容',
            summary: '初始输出 "3" 同时兼容 0+1+2=3 与 1+2=3 两种心智模型',
            sourceRef: '#att_01_init',
          },
          {
            id: 'ev_102',
            polarity: 'missing',
            polarityLabel: '缺失证据',
            summary: '缺少首轮进入循环体时 i 与 total 的中间打印值',
            sourceRef: '待追问验证',
          },
        ],
      },
      {
        hypothesisCode: 'H2: loop_memorized_without_trace',
        title: '仅凭直觉或记忆给出数字，未执行逐轮状态追踪',
        description: '学习者未写出任何每轮变量变化，可能直接猜测常见小整数结果。',
        heuristicWeightPct: 48,
        confidenceIsHeuristic: true,
        status: 'insufficient_evidence',
        statusLabel: 'insufficient_evidence（待验）',
        badgeTone: 'amber',
        evidences: [
          {
            id: 'ev_103',
            polarity: 'supports',
            polarityLabel: '支持 +',
            summary: 'RuleEvaluator 检测到作答仅有单字符 "3"，无过程追踪词元',
            sourceRef: 'rule_check',
          },
          {
            id: 'ev_104',
            polarity: 'missing',
            polarityLabel: '缺失证据',
            summary: '需检验学习者能否写出循环体内部逐轮输出序列',
            sourceRef: '待追问验证',
          },
        ],
      },
      {
        hypothesisCode: 'H3: range_stop_inclusive',
        title: '误以为 range(3) 包含上界 3',
        description: '若包含上界 3 则结果为 6，与当前输出 "3" 冲突，暂列低权重备选。',
        heuristicWeightPct: 14,
        confidenceIsHeuristic: true,
        status: 'lowered',
        statusLabel: 'lowered（次要备选）',
        badgeTone: 'slate',
        evidences: [
          {
            id: 'ev_105',
            polarity: 'contradicts',
            polarityLabel: '反驳 −',
            summary: '提交值 "3" 不等于包含上界 3 时的累加和 6',
            sourceRef: '#att_01_init',
          },
        ],
      },
    ],
  },
  2: {
    stage: 2,
    shortLabel: '2. 竞争假设 & 证据不足',
    stageTitle: '第 2 步：并列维护竞争性错误假设 · 派发高区分度追问',
    sessionStatus: 'diagnosing',
    sessionStatusDisplay: 'diagnosing（诊断取证中）',
    knowledgeStatus: 'insufficient_evidence',
    topicMastered: false,
    uncertaintyCode: 'INSUFFICIENT_EVIDENCE',
    uncertaintyLabel: 'INSUFFICIENT_EVIDENCE（证据不足 · 需追问）',
    uncertaintyTone: 'amber',
    degradedMode: false,
    rawAttemptId: 'att_01_init',
    rawAttemptTimestamp: '16:10:04',
    rawAttemptText: '3',
    rawAttemptNote: '不可变原始作答快照已锁定；Agent 正在评估最具区分度的追问。',
    agentToolName: 'select_diagnostic_followup',
    agentDecisionReason:
      '当前 H1 (range_start_at_one, 38%) 与 H2 (loop_memorized_without_trace, 48%) 难分高下。白名单工具选择追问题 q_py_loop_followup_01：询问循环体内每轮 print(total) 的序列，一次作答即可同时区分 H1 与 H2。',
    agentNextExpectation:
      '请回答下方 Agent 区分性追问。不能跳过追问直接进入练习或迁移验证。',
    task: {
      questionId: 'q_py_loop_followup_01',
      questionVersion: 1,
      questionRole: 'diagnostic_followup',
      roleLabel: 'diagnostic_followup · Agent 区分性追问 (q_py_loop_followup_01)',
      promptTitle: '【Agent 区分性追问】如果把 print(total) 移入 for 循环内部，每一轮会依次打印什么？',
      promptDescription:
        '为什么问这个问题：若回答 "0, 1, 3" 说明理解正确；若回答 "1, 3" 则证明确实进行了逐轮累加（排除 H2），但首轮把 i 当成了 1（锁定 H1）。',
      codeLanguage: 'python3',
      codeSnippet: `total = 0\nfor i in range(3):\n    total = total + i\n    print(total)  # <-- 请写出每轮依次打印的值`,
      defaultDraft: '依次打印 1、3',
      recommendedInputs: [
        {
          label: '填入典型误区回应："依次打印 1、3"',
          value: '依次打印 1、3',
          hint: '反驳 H2（证明有追踪），同时强力支持并确诊 H1',
        },
        {
          label: '填入模糊回应："不确定，好像最后是 3"',
          value: '不确定，好像最后是 3',
          hint: '支持 H2（缺乏逐轮执行心智模型）',
        },
      ],
      primaryActionLabel: '提交区分性追问回应并更新证据链 (进入第 3 步) →',
    },
    hypotheses: [
      {
        hypothesisCode: 'H1: range_start_at_one',
        title: '误以为 range(n) 默认从 1 开始而非 0',
        description: '若首轮 i=1、次轮 i=2，则循环体内会依次打印 1、3（共两轮）。',
        heuristicWeightPct: 38,
        confidenceIsHeuristic: true,
        status: 'candidate',
        statusLabel: 'candidate（待追问裁决）',
        badgeTone: 'amber',
        evidences: [
          {
            id: 'ev_201',
            polarity: 'neutral',
            polarityLabel: '中立兼容',
            summary: '初始输出 "3" 与 1+2=3 兼容',
            sourceRef: '#att_01_init',
          },
          {
            id: 'ev_202',
            polarity: 'missing',
            polarityLabel: '关键待采集证据',
            summary: '等待 q_py_loop_followup_01 验证首轮打印值是否为 1',
            sourceRef: 'q_py_loop_followup_01',
          },
        ],
      },
      {
        hypothesisCode: 'H2: loop_memorized_without_trace',
        title: '仅凭直觉或记忆给出数字，未执行逐轮状态追踪',
        description: '若无法写出任何中间轮次输出，则支持该假设。',
        heuristicWeightPct: 48,
        confidenceIsHeuristic: true,
        status: 'insufficient_evidence',
        statusLabel: 'insufficient_evidence（待追问裁决）',
        badgeTone: 'amber',
        evidences: [
          {
            id: 'ev_203',
            polarity: 'supports',
            polarityLabel: '支持 +',
            summary: '初答仅单个数字 "3"，未体现过程追踪',
            sourceRef: 'rule_check',
          },
          {
            id: 'ev_204',
            polarity: 'missing',
            polarityLabel: '关键待采集证据',
            summary: '等待验证学习者能否给出多步累加序列',
            sourceRef: 'q_py_loop_followup_01',
          },
        ],
      },
      {
        hypothesisCode: 'H3: range_stop_inclusive',
        title: '误以为 range(3) 包含上界 3',
        description: '已被初始作答反驳，保持低权重观察。',
        heuristicWeightPct: 14,
        confidenceIsHeuristic: true,
        status: 'lowered',
        statusLabel: 'lowered（已降低）',
        badgeTone: 'slate',
        evidences: [
          {
            id: 'ev_205',
            polarity: 'contradicts',
            polarityLabel: '反驳 −',
            summary: '初答 "3" 不符合 1+2+3=6',
            sourceRef: '#att_01_init',
          },
        ],
      },
    ],
  },
  3: {
    stage: 3,
    shortLabel: '3. 区分性追问 ("1、3")',
    stageTitle: '第 3 步：追问新证据入链 · 排除盲猜假设并确诊 H1 卡点',
    sessionStatus: 'intervening',
    sessionStatusDisplay: 'diagnosing → intervening（针对性干预中）',
    knowledgeStatus: 'needs_practice',
    topicMastered: false,
    uncertaintyCode: 'LOW',
    uncertaintyLabel: 'LOW（高区分度证据已收敛）',
    uncertaintyTone: 'green',
    degradedMode: false,
    rawAttemptId: 'att_02_followup',
    rawAttemptTimestamp: '16:12:19',
    rawAttemptText: '依次打印 1、3',
    rawAttemptNote: '追问回应提供了清晰的二轮累加轨迹（1 -> 3），成为关键区分证据。',
    agentToolName: 'provide_targeted_explanation + assign_targeted_practice',
    agentDecisionReason:
      '学习者写出“依次打印 1、3”：1) 反驳了 H2（证明确实在心算累加而非盲猜，H2 权重降至 12%）；2) 强力支持并确认 H1（误把 range(3) 当作从 1 开始的 [1, 2]，H1 权重升至 86%）。立即提供概念纠偏并派发针对性练习。',
    agentNextExpectation:
      '阅读下方针对性概念边界对比解释后，确认进入第 4 步针对性练习。',
    task: {
      questionId: 'q_py_loop_practice_01',
      questionVersion: 1,
      questionRole: 'targeted_practice',
      roleLabel: 'targeted_explanation · 针对性概念纠偏与干预确认',
      promptTitle: '【针对性干预纠偏】单参数 range(stop) 默认从 0 开始，共执行 3 轮而非 2 轮',
      promptDescription:
        '请对比下方两组 range 边界语义差异，并在输入框记录你的理解摘要后进入针对性练习题：',
      codeLanguage: 'python3',
      codeSnippet: `# 1) 单参数默认 start = 0（左闭右开，共 3 轮）：\n# range(3)    -> 依次产生 i = 0, 1, 2  => 循环内打印 0, 1, 3\n\n# 2) 双参数显式指定 start = 1（左闭右开，共 2 轮）：\n# range(1, 3) -> 依次产生 i = 1, 2     => 循环内打印 1, 3`,
      defaultDraft: '理解了：range(3) 等价于 range(0, 3)，第 1 轮 i=0，所以共 3 轮依次打印 0, 1, 3。',
      recommendedInputs: [
        {
          label: '填入概念纠偏确认笔记',
          value: '理解了：range(3) 等价于 range(0, 3)，第 1 轮 i=0，所以共 3 轮依次打印 0, 1, 3。',
          hint: '确认理解概念干预，解锁第 4 步针对性练习',
        },
      ],
      primaryActionLabel: '完成概念纠偏确认，进入针对性练习 (第 4 步) →',
    },
    hypotheses: [
      {
        hypothesisCode: 'H1: range_start_at_one',
        title: '误以为 range(n) 默认从 1 开始而非 0',
        description: '已被追问证据 #att_02_followup 锁定为当前核心认知卡点。',
        heuristicWeightPct: 86,
        confidenceIsHeuristic: true,
        status: 'confirmed',
        statusLabel: 'confirmed（已确认核心卡点）',
        badgeTone: 'red',
        evidences: [
          {
            id: 'ev_301',
            polarity: 'neutral',
            polarityLabel: '中立兼容',
            summary: '初始输出 "3" 与 1+2=3 兼容',
            sourceRef: '#att_01_init',
          },
          {
            id: 'ev_302',
            polarity: 'supports',
            polarityLabel: '强力支持 +',
            summary: '追问回答 "依次打印 1、3" 直接证实首轮 i 被当作 1、次轮 i=2',
            sourceRef: '#att_02_followup',
          },
        ],
      },
      {
        hypothesisCode: 'H2: loop_memorized_without_trace',
        title: '仅凭直觉或记忆给出数字，未执行逐轮状态追踪',
        description: '追问回应展示了明确的累加过程，该假设被新证据反驳并下调。',
        heuristicWeightPct: 12,
        confidenceIsHeuristic: true,
        status: 'lowered',
        statusLabel: 'lowered（已被新证据反驳）',
        badgeTone: 'slate',
        evidences: [
          {
            id: 'ev_303',
            polarity: 'supports',
            polarityLabel: '历史支持 +',
            summary: '初答仅单个数字 "3"',
            sourceRef: '#att_01_init',
          },
          {
            id: 'ev_304',
            polarity: 'contradicts',
            polarityLabel: '新证据反驳 −',
            summary: '追问能准确写出两步累加中间态 "1、3"，并非盲目背答案',
            sourceRef: '#att_02_followup',
          },
        ],
      },
      {
        hypothesisCode: 'H3: range_stop_inclusive',
        title: '误以为 range(3) 包含上界 3',
        description: '追问序列在 3 结束（未加 i=3），进一步排除上界包含误区。',
        heuristicWeightPct: 8,
        confidenceIsHeuristic: true,
        status: 'lowered',
        statusLabel: 'lowered（已排除）',
        badgeTone: 'slate',
        evidences: [
          {
            id: 'ev_305',
            polarity: 'contradicts',
            polarityLabel: '反驳 −',
            summary: '初答与追问均未将 i=3 纳入累加',
            sourceRef: '#att_02_followup',
          },
        ],
      },
    ],
  },
  4: {
    stage: 4,
    shortLabel: '4. 针对性干预 & 练习',
    stageTitle: '第 4 步：完成针对性练习 · 准备进入独立迁移验证',
    sessionStatus: 'intervening',
    sessionStatusDisplay: 'intervening → transfer_checking',
    knowledgeStatus: 'needs_practice',
    topicMastered: false,
    uncertaintyCode: 'MEDIUM',
    uncertaintyLabel: 'MEDIUM（练习待验，尚未跨情境迁移）',
    uncertaintyTone: 'blue',
    degradedMode: false,
    rawAttemptId: 'att_03_practice',
    rawAttemptTimestamp: '16:15:40',
    rawAttemptText: '6（第 1 轮 i=1, 第 2 轮 i=2, 第 3 轮 i=3，相加得 6）',
    rawAttemptNote: '针对性练习正确区分了显式起始边界 range(1, 4) 的左闭右开语义。',
    agentToolName: 'assign_transfer_verification',
    agentDecisionReason:
      '学习者在针对性练习 q_py_loop_practice_01 中正确输出 6，H1 风险从 86% 缓解至 35%。但根据 VerbaTrail 核心不变量：同结构练习答对不等于掌握，必须通过新情境迁移验证题才能晋升 stable。',
    agentNextExpectation:
      '提交针对性练习答案后，系统将切换会话至 transfer_checking 并派发迁移验证题 #1。',
    task: {
      questionId: 'q_py_loop_practice_01',
      questionVersion: 1,
      questionRole: 'targeted_practice',
      roleLabel: 'targeted_practice · 针对性边界练习 (q_py_loop_practice_01)',
      promptTitle: '【针对性练习】当循环显式指定 range(1, 4) 时，最终 print(total) 输出什么？',
      promptDescription:
        '请写出最终输出值及每轮 i 的取值（提示：注意左闭右开区间 [1, 4) 包含哪些整数）：',
      codeLanguage: 'python3',
      codeSnippet: `total = 0\nfor i in range(1, 4):\n    total += i\nprint(total)`,
      defaultDraft: '6（第1轮 i=1, 第2轮 i=2, 第3轮 i=3，相加得 6）',
      recommendedInputs: [
        {
          label: '填入正确练习作答："6（i=1, 2, 3 相加得 6）"',
          value: '6（第1轮 i=1, 第2轮 i=2, 第3轮 i=3，相加得 6）',
          hint: '通过针对性练习，合法解锁第 5 步变式迁移验证',
        },
      ],
      primaryActionLabel: '提交针对性练习并派发迁移验证题 (进入第 5 步) →',
    },
    hypotheses: [
      {
        hypothesisCode: 'H1: range_start_at_one',
        title: '误以为 range(n) 默认从 1 开始而非 0',
        description: '经过概念纠偏与显式起止边界练习，风险已下降，但仍需跨情境验证。',
        heuristicWeightPct: 35,
        confidenceIsHeuristic: true,
        status: 'lowered',
        statusLabel: 'lowered（干预后已缓解）',
        badgeTone: 'blue',
        evidences: [
          {
            id: 'ev_401',
            polarity: 'supports',
            polarityLabel: '历史支持 +',
            summary: '追问 #att_02_followup 曾将 range(3) 当作 [1, 2]',
            sourceRef: '#att_02_followup',
          },
          {
            id: 'ev_402',
            polarity: 'contradicts',
            polarityLabel: '练习反驳 −',
            summary: '针对性练习 range(1, 4) 正确追踪 i=1,2,3 输出 6',
            sourceRef: '#att_03_practice',
          },
          {
            id: 'ev_403',
            polarity: 'missing',
            polarityLabel: '待迁移验证',
            summary: '尚缺少在新表面结构（含步长与双变量）下的独立首次正确证据',
            sourceRef: '待 transfer_check',
          },
        ],
      },
      {
        hypothesisCode: 'H2: loop_memorized_without_trace',
        title: '仅凭直觉或记忆给出数字，未执行逐轮状态追踪',
        description: '练习中附带完整三轮追踪，维持低风险。',
        heuristicWeightPct: 12,
        confidenceIsHeuristic: true,
        status: 'lowered',
        statusLabel: 'lowered（已降低）',
        badgeTone: 'slate',
        evidences: [
          {
            id: 'ev_404',
            polarity: 'contradicts',
            polarityLabel: '反驳 −',
            summary: '追问与练习均提供了完整逐轮变量追踪',
            sourceRef: '#att_03_practice',
          },
        ],
      },
    ],
  },
  5: {
    stage: 5,
    shortLabel: '5. 迁移验证 & 同题拦截',
    stageTitle: '第 5 步：迁移验证失败 + 同题重试防刷分拦截 (transfer_retry_blocked)',
    sessionStatus: 'transfer_checking',
    sessionStatusDisplay: 'transfer_checking（迁移验证防刷分保护中）',
    knowledgeStatus: 'needs_practice',
    topicMastered: false,
    uncertaintyCode: 'MEDIUM',
    uncertaintyLabel: 'MEDIUM（同题重试被拦截，需独立新题）',
    uncertaintyTone: 'amber',
    degradedMode: false,
    rawAttemptId: 'att_05_same_retry',
    rawAttemptTimestamp: '16:19:02',
    rawAttemptText: '3 15 (首次失败 #att_04) → 3 17 (同题重答 #att_05，被拦截)',
    rawAttemptNote: '检测到同一道迁移题 q_py_loop_transfer_01 存在历史失败记录 #att_04，拒绝将同题重答作为掌握证据。',
    agentToolName: 'transfer_retry_blocked (Stage 3/4 领域不变量)',
    agentDecisionReason:
      '学习者在迁移题 #1 (q_py_loop_transfer_01) 首次作答提交 "3 15" 失败；随后对同一道题重试提交正确答案 "3 17"。根据 Stage 3/4 防刷分规则：同题重复作答无法排除试错或背答案，系统拒绝晋升 stable，保持 needs_practice，并要求派发从未作答过的独立新迁移题 #2。',
    agentNextExpectation:
      '请点击下方按钮请求系统派发全新情境迁移题 q_py_loop_transfer_02（进入第 6 步）。',
    task: {
      questionId: 'q_py_loop_transfer_01',
      questionVersion: 1,
      questionRole: 'transfer_check',
      roleLabel: 'transfer_check · 迁移题 #1 (q_py_loop_transfer_01 · 已被同题失败污染)',
      promptTitle: '【迁移题 #1 · 仓库双变量盘点】首次答错 "3 15" 后，同题重答 "3 17" 已被系统拦截晋升：',
      promptDescription:
        '你可以在下方体验提交同题重答或前往“变式迁移验证室”交互体验完整三步防刷分机制，然后派发全新迁移题 #2：',
      codeLanguage: 'python3',
      codeSnippet: `count = 0\nrunning_sum = 5\nfor step in range(1, 7, 2):\n    count += 1\n    running_sum += step * 2\nprint(count, running_sum)`,
      defaultDraft: '3 17',
      recommendedInputs: [
        {
          label: '模拟首次错误作答："3 15"',
          value: '3 15',
          hint: '触发 needs_practice 与间隔复习计划 ReviewItem',
        },
        {
          label: '模拟同题第二次重答正确答案："3 17"',
          value: '3 17',
          hint: '触发 transfer_retry_blocked 拦截，拒绝晋升 stable',
        },
      ],
      primaryActionLabel: '派发未作答过的独立新迁移题 q_py_loop_transfer_02 (进入第 6 步) →',
    },
    hypotheses: [
      {
        hypothesisCode: 'H1: range_start_at_one',
        title: '误以为 range(n) 默认从 1 开始而非 0 / 步长累加偏差',
        description: '同题重答 "3 17" 不能排除记忆答案效应，因此必须由未污染的新题验证。',
        heuristicWeightPct: 35,
        confidenceIsHeuristic: true,
        status: 'lowered',
        statusLabel: 'lowered（待独立新题最终验证）',
        badgeTone: 'amber',
        evidences: [
          {
            id: 'ev_501',
            polarity: 'contradicts',
            polarityLabel: '练习反驳 −',
            summary: '针对性练习 q_py_loop_practice_01 作答正确',
            sourceRef: '#att_03_practice',
          },
          {
            id: 'ev_502',
            polarity: 'supports',
            polarityLabel: '迁移受阻 +',
            summary: '迁移题 #1 首次作答 "3 15" 累加有误，触发复习队列',
            sourceRef: '#att_04_transfer_fail',
          },
          {
            id: 'ev_503',
            polarity: 'missing',
            polarityLabel: '同题重答被拒',
            summary: '同题重答 #att_05 ("3 17") 被 transfer_retry_blocked 拦截，需新题首次正确证据',
            sourceRef: '#att_05_same_retry',
          },
        ],
      },
      {
        hypothesisCode: 'H2: loop_memorized_without_trace',
        title: '仅凭直觉或记忆给出数字，未执行逐轮状态追踪',
        description: '同题重试存在背诵答案风险，防刷分守卫已生效。',
        heuristicWeightPct: 24,
        confidenceIsHeuristic: true,
        status: 'insufficient_evidence',
        statusLabel: 'insufficient_evidence（防刷分锁定）',
        badgeTone: 'amber',
        evidences: [
          {
            id: 'ev_504',
            polarity: 'supports',
            polarityLabel: '风险提示 +',
            summary: '同一道迁移题重复提交无法排除记忆答案',
            sourceRef: 'transfer_guard',
          },
        ],
      },
    ],
  },
  6: {
    stage: 6,
    shortLabel: '6. 独立新题掌握 (stable)',
    stageTitle: '第 6 步：独立新情境迁移验证首次通过 · 合法晋升操作性掌握 (stable)',
    sessionStatus: 'completed',
    sessionStatusDisplay: 'transfer_checking → completed (topic_mastered=true)',
    knowledgeStatus: 'stable',
    topicMastered: true,
    uncertaintyCode: 'LOW',
    uncertaintyLabel: 'LOW（独立新题首次验证通过）',
    uncertaintyTone: 'green',
    degradedMode: false,
    rawAttemptId: 'att_06_fresh_transfer',
    rawAttemptTimestamp: '16:22:15',
    rawAttemptText: '3 60（tick=2,4,6 共 3 轮；energy = 15 + 6 + 12 + 18 = 51? 等等：15 + 2*3 + 4*3 + 6*3 = 15 + 6 + 12 + 18 = 51 / 含初始偏置校核通过）',
    rawAttemptNote: '在从未接触过的独立新迁移题 q_py_loop_transfer_02 上首次独立作答即通过规则与证据链校验。',
    agentToolName: 'update_knowledge_state (target_status="stable")',
    agentDecisionReason:
      '学习者在全新表面结构迁移题 q_py_loop_transfer_02（温控传感器能量采样）中首次独立作答正确。满足 Stage 3/4 完整证据链（已确认假设被缓解 + 针对性干预完成 + 独立未污染新迁移题首次答对），KnowledgeState 合法更新为 stable（操作性掌握，非永久绝对掌握）。',
    agentNextExpectation:
      '当前闭环已完成！可前往“掌握状态与复习计划”查看 session.status 与 KnowledgeState.status 的严格对比。',
    task: {
      questionId: 'q_py_loop_transfer_02',
      questionVersion: 1,
      questionRole: 'transfer_check',
      roleLabel: 'transfer_check · 独立新迁移题 #2 (q_py_loop_transfer_02 · 全新情境)',
      promptTitle: '【独立新迁移题 #2 · 传感器采样累加】首次独立作答验证通过：',
      promptDescription:
        '表面情境更换为传感器周期采样，底层仍检验 range(start, stop, step) 边界与双变量状态累加：',
      codeLanguage: 'python3',
      codeSnippet: `alerts = 0\nenergy = 24\nfor tick in range(2, 8, 2):\n    alerts += 1\n    energy += tick * 3\nprint(alerts, energy)`,
      defaultDraft: '3 60（tick 依次取 2, 4, 6 共 3 轮；energy = 24 + 6 + 12 + 18 = 60）',
      recommendedInputs: [
        {
          label: '填入新迁移题 #2 首次正确作答："3 60"',
          value: '3 60（tick 依次取 2, 4, 6 共 3 轮；energy = 24 + 6 + 12 + 18 = 60）',
          hint: '独立新题首次通过，合法晋升 stable',
        },
      ],
      primaryActionLabel: '查看知识点掌握状态与会话语义矩阵 →',
    },
    hypotheses: [
      {
        hypothesisCode: 'H1: range_start_at_one',
        title: '误以为 range(n) 默认从 1 开始而非 0',
        description: '经独立新情境迁移题首次验证通过，该错误假设已解决。',
        heuristicWeightPct: 10,
        confidenceIsHeuristic: true,
        status: 'resolved',
        statusLabel: 'lowered（新题迁移验证已解决）',
        badgeTone: 'green',
        evidences: [
          {
            id: 'ev_601',
            polarity: 'contradicts',
            polarityLabel: '新题验证反驳 −',
            summary: '独立新迁移题 q_py_loop_transfer_02 首次作答正确输出 "3 60"',
            sourceRef: '#att_06_fresh_transfer',
          },
        ],
      },
      {
        hypothesisCode: 'H2: loop_memorized_without_trace',
        title: '仅凭直觉或记忆给出数字，未执行逐轮状态追踪',
        description: '全新题目无历史失败记录，首次独立追踪正确，排除背答案可能。',
        heuristicWeightPct: 8,
        confidenceIsHeuristic: true,
        status: 'resolved',
        statusLabel: 'lowered（已排除记忆效应）',
        badgeTone: 'green',
        evidences: [
          {
            id: 'ev_602',
            polarity: 'contradicts',
            polarityLabel: '独立新题反驳 −',
            summary: 'q_py_loop_transfer_02 无历史提交记录，首次作答即完整给出 tick=2,4,6 累加过程',
            sourceRef: '#att_06_fresh_transfer',
          },
        ],
      },
    ],
  },
};

export const INITIAL_DECISION_TIMELINE: DecisionTimelineItemView[] = [
  {
    eventId: 'evt_881',
    stageReachableAt: 1,
    toolName: 'rule_pre_evaluation',
    summary: '初答 "3" 缺少逐轮追踪证据，生成 H1/H2/H3 并列竞争假设，拒绝武断归因',
    outcomeCode: 'INSUFFICIENT_EVIDENCE',
    badgeTone: 'amber',
    timestamp: '16:10:05',
  },
  {
    eventId: 'evt_882',
    stageReachableAt: 2,
    toolName: 'select_diagnostic_followup',
    summary: '为区分 H1 (range_start_at_one) 与 H2 (盲猜无追踪)，派发低成本追问 q_py_loop_followup_01',
    outcomeCode: 'QUESTION_SELECTED',
    badgeTone: 'blue',
    timestamp: '16:10:06',
  },
  {
    eventId: 'evt_885',
    stageReachableAt: 3,
    toolName: 'provide_targeted_explanation',
    summary: '追问回应 "依次打印 1、3" 反驳 H2 并确诊 H1 (86%)，触发概念纠偏与针对性练习',
    outcomeCode: 'INTERVENTION_SELECTED',
    badgeTone: 'purple',
    timestamp: '16:12:20',
  },
  {
    eventId: 'evt_887',
    stageReachableAt: 4,
    toolName: 'assign_transfer_verification',
    summary: '针对性练习 q_py_loop_practice_01 通过，H1 缓解至 35%，派发迁移题 q_py_loop_transfer_01',
    outcomeCode: 'TRANSFER_ASSIGNED',
    badgeTone: 'blue',
    timestamp: '16:15:42',
  },
  {
    eventId: 'evt_889',
    stageReachableAt: 5,
    toolName: 'transfer_retry_blocked',
    summary: '迁移题 #1 首次答错后同题重答 "3 17"，防刷分守卫拦截晋升 stable，保持 needs_practice',
    outcomeCode: 'TRANSFER_RETRY_BLOCKED',
    badgeTone: 'amber',
    timestamp: '16:19:03',
  },
  {
    eventId: 'evt_890',
    stageReachableAt: 6,
    toolName: 'update_knowledge_state',
    summary: '独立新迁移题 q_py_loop_transfer_02 首次作答 "3 60" 通过，KnowledgeState 合法更新为 stable',
    outcomeCode: 'RESOLVED_STABLE',
    badgeTone: 'green',
    timestamp: '16:22:16',
  },
];

export const INITIAL_TOPIC_MASTERY_MATRIX: TopicMasteryMatrixItem[] = [
  {
    topicSlug: 'py-variables-types',
    topicTitle: '变量绑定与基本数据类型',
    prerequisiteSlugs: [],
    sessionStatus: 'completed',
    knowledgeStatus: 'stable',
    topicMastered: true,
    completionReason: 'mastery_achieved',
    confidenceScore: 0.88,
    confidenceIsHeuristic: true,
    lastEvidenceSummary: '独立迁移题 q_py_var_transfer_01 首次验证通过 (#att_09)',
    reviewDueStatus: 'none',
  },
  {
    topicSlug: 'py-for-loop',
    topicTitle: 'for 循环、range 边界与状态累加器',
    prerequisiteSlugs: ['py-variables-types'],
    sessionStatus: 'diagnosing',
    knowledgeStatus: 'insufficient_evidence',
    topicMastered: false,
    completionReason: 'in_progress_session',
    confidenceScore: 0.42,
    confidenceIsHeuristic: true,
    lastEvidenceSummary: '当前工作台活跃会话 · 随 1~6 步闭环推进实时更新状态',
    reviewDueStatus: 'due_now',
    reviewItemId: 'rev_loop_01',
    reviewReason: '迁移题 #1 (q_py_loop_transfer_01) 曾首次验证失败，待间隔复习巩固 range 步长边界',
  },
  {
    topicSlug: 'py-list-reference',
    topicTitle: '列表可变引用与浅拷贝别名效应',
    prerequisiteSlugs: ['py-variables-types', 'py-for-loop'],
    sessionStatus: 'completed',
    knowledgeStatus: 'needs_practice',
    topicMastered: false,
    completionReason: 'session_completed_without_mastery',
    confidenceScore: 0.36,
    confidenceIsHeuristic: true,
    lastEvidenceSummary: '迁移验证未通过后学习者主动结束会话 (session.status=completed 但 topic_mastered=false)',
    reviewDueStatus: 'due_now',
    reviewItemId: 'rev_list_02',
    reviewReason: '混淆 a = b 引用别名与 a = b[:] 切片浅拷贝，需优先完成复习与新题验证',
  },
  {
    topicSlug: 'py-if-elif-else',
    topicTitle: '条件分支互斥与布尔短路求值',
    prerequisiteSlugs: ['py-variables-types'],
    sessionStatus: 'paused',
    knowledgeStatus: 'insufficient_evidence',
    topicMastered: false,
    completionReason: 'user_paused_during_diagnosis',
    confidenceScore: 0.30,
    confidenceIsHeuristic: true,
    lastEvidenceSummary: '会话已暂停 (paused) · 存在 2 个竞争性分支覆盖假设等待追问取证',
    reviewDueStatus: 'scheduled',
    reviewItemId: 'rev_cond_03',
    reviewReason: '多个 if 独立判断与 if-elif 互斥链区分证据不足',
  },
  {
    topicSlug: 'py-function-return',
    topicTitle: '函数返回值与 print 副作用区分',
    prerequisiteSlugs: ['py-for-loop', 'py-if-elif-else'],
    sessionStatus: 'completed',
    knowledgeStatus: 'stable',
    topicMastered: true,
    completionReason: 'mastery_achieved',
    confidenceScore: 0.85,
    confidenceIsHeuristic: true,
    lastEvidenceSummary: '完成追问纠偏与独立新情境迁移验证 (#att_14)，当前阶段表现为操作性稳定',
    reviewDueStatus: 'scheduled',
  },
];
