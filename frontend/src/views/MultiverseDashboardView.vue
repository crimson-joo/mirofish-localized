<template>
  <div class="multiverse-view">
    <header class="mv-header">
      <div>
        <div class="brand" @click="router.push('/')">MIROFISH</div>
        <p class="eyebrow">Multiverse Simulation</p>
        <h1>멀티버스 시뮬레이션 대시보드</h1>
        <p class="subtitle">여러 가능세계의 준비/실행 상태와 ensemble_frequency 결과를 한 화면에서 확인합니다.</p>
      </div>
      <div class="header-actions">
        <LanguageSwitcher />
        <button class="ghost-btn" @click="loadAll">새로고침</button>
      </div>
    </header>

    <main v-if="experiment" class="mv-content">
      <section class="summary-grid">
        <div class="summary-card">
          <span class="label">상태</span>
          <strong>{{ experiment.status }}</strong>
        </div>
        <div class="summary-card">
          <span class="label">세계선</span>
          <strong>{{ experiment.universe_count }}</strong>
        </div>
        <div class="summary-card">
          <span class="label">동시 실행</span>
          <strong>{{ experiment.max_parallel }}</strong>
        </div>
        <div class="summary-card">
          <span class="label">Rounds</span>
          <strong>{{ experiment.rounds }}</strong>
        </div>
      </section>

      <section class="control-panel">
        <div>
          <h2>실행 컨트롤</h2>
          <p>기본값은 Core persona, Graph memory ON, 24 rounds, max_parallel=2입니다.</p>
        </div>
        <div class="control-actions">
          <button class="primary-btn" :disabled="busy" @click="prepareExperiment">Async Prepare Queue</button>
          <button class="primary-btn accent" :disabled="busy" @click="startExperiment">Run Queue</button>
          <button class="ghost-btn" :disabled="busy" @click="advanceExperiment">Auto-advance</button>
          <button class="ghost-btn" :disabled="busy" @click="loadReport">Semantic Aggregate</button>
          <button class="ghost-btn" :disabled="busy" @click="loadComparison">단일 vs 멀티버스 비교</button>
        </div>
      </section>

      <section v-if="prepareTask || aggregate?.progress" class="progress-panel">
        <div>
          <p class="eyebrow">Progress</p>
          <h2>Prepare / Run 진행률</h2>
        </div>
        <div class="progress-grid">
          <div v-if="prepareTask" class="summary-card wide">
            <span class="label">Prepare task</span>
            <strong>{{ prepareTask.status }} · {{ prepareTask.progress }}%</strong>
            <p>{{ prepareTask.message }}</p>
          </div>
          <div v-if="aggregate?.progress" class="summary-card wide">
            <span class="label">Run progress</span>
            <strong>{{ aggregate.progress.completed }}/{{ aggregate.progress.total }} completed</strong>
            <p>running {{ aggregate.progress.running }} · ready {{ aggregate.progress.ready }} · queued {{ aggregate.progress.queued }} · failed {{ aggregate.progress.failed }}</p>
          </div>
        </div>
      </section>

      <section class="universe-grid">
        <article v-for="child in experiment.children" :key="child.universe_id" class="universe-card">
          <div class="universe-topline">
            <span class="universe-id">{{ child.universe_id }}</span>
            <span class="status-pill" :class="child.status">{{ child.status }}</span>
          </div>
          <h3>{{ child.scenario_variant?.label || child.name }}</h3>
          <p>{{ child.scenario_variant?.assumption }}</p>
          <dl>
            <div><dt>Polarity</dt><dd>{{ child.scenario_variant?.polarity }}</dd></div>
            <div><dt>Persona</dt><dd>{{ child.persona_variation?.mode }} / {{ child.persona_variation?.variance }}</dd></div>
            <div><dt>Simulation</dt><dd>{{ child.simulation_id }}</dd></div>
          </dl>
          <button class="link-btn" @click="router.push({ name: 'SimulationRun', params: { simulationId: child.simulation_id } })">child simulation 보기 →</button>
        </article>
      </section>


      <section class="comparison-panel" data-testid="multiverse-comparison-panel">
        <div class="report-header">
          <div>
            <p class="eyebrow">Single vs Multiverse</p>
            <h2>단일 실행 대비 개선 판단</h2>
          </div>
          <button class="primary-btn" :disabled="busy" @click="loadComparison">비교 새로고침</button>
        </div>
        <div v-if="comparison" class="comparison-grid">
          <div class="summary-card">
            <span class="label">판정</span>
            <strong :class="comparison.judgement?.verdict === 'PASS' ? 'pass-text' : 'warn-text'">{{ comparison.judgement?.verdict }}</strong>
            <p>{{ comparison.judgement?.caveat }}</p>
          </div>
          <div class="summary-card">
            <span class="label">단일 기준</span>
            <strong>{{ comparison.single?.evidence_items || 0 }} evidence</strong>
            <p>{{ baselineSource?.source_label || '첫 완료 universe' }} · {{ baselineSource?.universe_id || 'pending' }}</p>
          </div>
          <div class="summary-card">
            <span class="label">멀티버스</span>
            <strong>{{ comparison.multiverse?.improvement_score || 0 }} score</strong>
            <p>cluster {{ comparison.multiverse?.cluster_count || 0 }} · axis {{ comparison.multiverse?.sensitivity_axis_count || 0 }}</p>
          </div>
          <div class="summary-card wide">
            <span class="label">왜 좋아졌나</span>
            <p>{{ comparison.judgement?.why }}</p>
          </div>
        </div>
        <p v-else class="empty-state">비교 새로고침을 누르면 단일 실행 baseline과 멀티버스 결과를 PASS/WARN/FAIL로 비교합니다.</p>
      </section>

      <section class="report-agent-panel" data-testid="multiverse-report-agent-panel">
        <div class="report-header">
          <div>
            <p class="eyebrow">Report Agent</p>
            <h2>보고서 AI(Report Agent)에게 묻기</h2>
          </div>
        </div>
        <div class="agent-context-grid">
          <div class="summary-card wide">
            <span class="label">현재 주제</span>
            <p>{{ reportAgentContext?.base_requirement || experiment.base_requirement }}</p>
          </div>
          <div class="summary-card">
            <span class="label">리포트 상태</span>
            <strong>{{ reportStatus.completed_count }}/{{ reportStatus.universe_count }}</strong>
            <p>cluster {{ reportStatus.cluster_count }} · axis {{ reportStatus.sensitivity_axis_count }}</p>
          </div>
          <div class="summary-card">
            <span class="label">비교 기준</span>
            <strong>{{ baselineSource?.universe_id || 'pending' }}</strong>
            <p>{{ baselineSource?.reason || '첫 완료 universe를 단일 기준으로 사용합니다.' }}</p>
          </div>
        </div>
        <div class="suggested-question-list">
          <button
            v-for="item in contextualSuggestedQuestions"
            :key="`${item.category}-${item.question}`"
            class="suggested-question-card"
            :disabled="busy"
            @click="askQuestion(item.question)"
          >
            <span class="question-label">{{ item.label || item.category }}</span>
            <strong>{{ item.question }}</strong>
            <small>{{ item.reason }}</small>
          </button>
        </div>
        <div class="agent-input-row">
          <input v-model="agentQuestion" placeholder="예: 현재 리포트의 핵심 결론은 뭐야?" @keyup.enter="askQuestion(agentQuestion)" />
          <button class="primary-btn" :disabled="busy || !agentQuestion" @click="askQuestion(agentQuestion)">질문</button>
        </div>
        <div v-if="agentAnswer" class="agent-answer">{{ agentAnswer }}</div>
      </section>

      <section class="report-panel">
        <div class="report-header">
          <div>
            <p class="eyebrow">Aggregate</p>
            <h2>결과 분포 / 민감도 / 보고서</h2>
          </div>
          <span class="note">실제 확률이 아니라 simulation branch의 ensemble_frequency</span>
        </div>
        <div v-if="aggregate" class="aggregate-grid">
          <div class="summary-card">
            <span class="label">Completed</span>
            <strong>{{ aggregate.completed_count }}</strong>
          </div>
          <div class="summary-card">
            <span class="label">Failed</span>
            <strong>{{ aggregate.failed_count }}</strong>
          </div>
          <div class="summary-card wide">
            <span class="label">Status frequency</span>
            <strong>{{ JSON.stringify(aggregate.status_frequency || {}) }}</strong>
          </div>
        </div>
        <div v-if="aggregate?.outcome_clusters?.length" class="cluster-list">
          <h3>Outcome clusters</h3>
          <div v-for="cluster in aggregate.outcome_clusters" :key="cluster.cluster_id" class="cluster-chip">
            <strong>{{ cluster.label }}</strong>
            <span>{{ cluster.ensemble_frequency }}</span>
          </div>
        </div>
        <pre v-if="reportMarkdown" class="report-markdown">{{ reportMarkdown }}</pre>
        <p v-else class="empty-state">Aggregate Report를 누르면 공통/분기/민감도 보고서가 생성됩니다.</p>
      </section>
    </main>

    <div v-else class="loading-state">멀티버스 실험을 불러오는 중...</div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import {
  advanceMultiverse,
  getMultiverse,
  getMultiversePrepareStatus,
  getMultiverseReport,
  getMultiverseStatus,
  compareMultiverseWithSingle,
  chatMultiverseReportAgent,
  prepareMultiverse,
  startMultiverse
} from '../api/simulation'

const route = useRoute()
const router = useRouter()
const multiverseId = computed(() => route.params.multiverseId)
const experiment = ref(null)
const aggregate = ref(null)
const reportMarkdown = ref('')
const comparison = ref(null)
const agentQuestion = ref('현재 리포트의 핵심 결론은 뭐야?')
const agentAnswer = ref('')
const fallbackSuggestedQuestions = [
  {
    category: 'topic',
    label: '주제 핵심',
    question: '현재 주제에서 리포트가 말하는 핵심 결론은 뭐야?',
    reason: '아직 backend 추천 질문이 로딩되지 않았을 때 사용하는 기본 질문입니다.'
  },
  {
    category: 'single_vs_multiverse',
    label: '단일 대비',
    question: '단일 기준으로 봤다면 놓쳤을 멀티버스 결론은 뭐야?',
    reason: '첫 완료 universe baseline과 멀티버스 aggregate의 차이를 확인합니다.'
  },
  {
    category: 'sensitivity',
    label: '분기/민감도',
    question: '어떤 조건에서 결과가 갈렸어?',
    reason: 'sensitivity axis가 결과 차이를 만든 조건인지 확인합니다.'
  }
]
const reportAgentContext = computed(() => comparison.value?.report_agent_context || aggregate.value?.report_agent_context || {})
const baselineSource = computed(() => comparison.value?.single?.baseline_source || aggregate.value?.single_baseline || reportAgentContext.value?.single_baseline || null)
const reportStatus = computed(() => reportAgentContext.value?.report_status || {
  completed_count: aggregate.value?.completed_count || 0,
  universe_count: aggregate.value?.universe_count || experiment.value?.universe_count || 0,
  cluster_count: aggregate.value?.outcome_clusters?.length || 0,
  sensitivity_axis_count: aggregate.value?.sensitivity_axes?.length || 0
})
const contextualSuggestedQuestions = computed(() => {
  const questions = reportAgentContext.value?.suggested_questions || []
  return questions.length ? questions : fallbackSuggestedQuestions
})
const prepareTask = ref(null)
const busy = ref(false)
let pollTimer = null

const loadExperiment = async () => {
  const res = await getMultiverse(multiverseId.value)
  experiment.value = res.data
  aggregate.value = res.data?.aggregate && Object.keys(res.data.aggregate).length ? res.data.aggregate : aggregate.value
}

const refreshStatus = async () => {
  const res = await getMultiverseStatus(multiverseId.value)
  if (res.success && res.data?.experiment) {
    experiment.value = res.data.experiment
  }
}

const loadReport = async () => {
  busy.value = true
  try {
    const res = await getMultiverseReport(multiverseId.value, { clustering_strategy: 'semantic' })
    aggregate.value = res.data.aggregate
    reportMarkdown.value = res.data.report_markdown
    await loadExperiment()
  } finally {
    busy.value = false
  }
}

const prepareExperiment = async () => {
  busy.value = true
  try {
    const res = await prepareMultiverse(multiverseId.value, { use_llm_for_profiles: true, async: true })
    if (res.data?.task_id) {
      const taskRes = await getMultiversePrepareStatus(multiverseId.value, res.data.task_id)
      prepareTask.value = taskRes.data
    }
    await loadExperiment()
  } finally {
    busy.value = false
  }
}

const startExperiment = async () => {
  busy.value = true
  try {
    await startMultiverse(multiverseId.value, { platform: 'parallel' })
    await refreshStatus()
  } finally {
    busy.value = false
  }
}

const advanceExperiment = async () => {
  busy.value = true
  try {
    await advanceMultiverse(multiverseId.value, { platform: 'parallel' })
    await refreshStatus()
    await loadReport()
  } finally {
    busy.value = false
  }
}


const loadComparison = async () => {
  busy.value = true
  try {
    const res = await compareMultiverseWithSingle(multiverseId.value, { clustering_strategy: 'semantic', use_llm: false })
    comparison.value = res.data
    aggregate.value = res.data?.aggregate || aggregate.value
    reportMarkdown.value = res.data?.report_markdown || reportMarkdown.value
  } finally {
    busy.value = false
  }
}

const askQuestion = async (question) => {
  if (!question) return
  busy.value = true
  agentQuestion.value = question
  try {
    const res = await chatMultiverseReportAgent(multiverseId.value, { message: question, clustering_strategy: 'semantic', use_llm: false })
    agentAnswer.value = res.data?.response || ''
    comparison.value = comparison.value || { multiverse: {}, judgement: res.data?.comparison || {} }
  } finally {
    busy.value = false
  }
}

const loadAll = async () => {
  await refreshStatus()
  await loadExperiment()
}

onMounted(async () => {
  await loadExperiment()
  await loadComparison()
  pollTimer = setInterval(refreshStatus, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.multiverse-view {
  min-height: 100vh;
  background: #090a0f;
  color: #f4f7fb;
  padding: 28px;
}
.mv-header, .control-panel, .report-header {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: center;
}
.brand { font-weight: 800; letter-spacing: 0.18em; cursor: pointer; color: #8de8ff; }
.eyebrow { color: #8de8ff; text-transform: uppercase; letter-spacing: .16em; font-size: 12px; margin: 8px 0; }
h1, h2, h3 { margin: 0; }
.subtitle, .control-panel p, .universe-card p, .note, .empty-state { color: #96a3b8; }
.header-actions, .control-actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.mv-content { margin-top: 28px; display: flex; flex-direction: column; gap: 22px; }
.summary-grid, .aggregate-grid, .progress-grid { display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 14px; }
.summary-card, .control-panel, .progress-panel, .universe-card, .report-panel {
  background: rgba(255,255,255,0.055);
  border: 1px solid rgba(141,232,255,0.18);
  border-radius: 18px;
  padding: 18px;
  box-shadow: 0 18px 45px rgba(0,0,0,.22);
}
.summary-card .label { display:block; color:#96a3b8; font-size:12px; margin-bottom:8px; }
.summary-card strong { font-size: 24px; }
.summary-card.wide { grid-column: span 2; }
.primary-btn, .ghost-btn, .link-btn {
  border-radius: 999px;
  border: 1px solid rgba(141,232,255,.4);
  padding: 10px 16px;
  color: #f4f7fb;
  background: rgba(141,232,255,.12);
  cursor: pointer;
}
.primary-btn { background: linear-gradient(135deg, #2dd4bf, #38bdf8); color: #041014; font-weight: 700; }
.primary-btn.accent { background: linear-gradient(135deg, #fbbf24, #fb7185); }
button:disabled { opacity: .45; cursor: wait; }
.universe-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
.universe-topline { display:flex; justify-content:space-between; align-items:center; margin-bottom: 12px; }
.universe-id { color:#8de8ff; font-weight:700; }
.status-pill { padding: 4px 10px; border-radius: 999px; background: rgba(148,163,184,.22); font-size: 12px; }
.status-pill.ready, .status-pill.completed { background: rgba(34,197,94,.25); color:#86efac; }
.status-pill.running, .status-pill.preparing { background: rgba(59,130,246,.25); color:#93c5fd; }
.status-pill.failed { background: rgba(239,68,68,.25); color:#fca5a5; }
dl { display:grid; gap:8px; margin:16px 0; }
dt { color:#96a3b8; font-size:12px; }
dd { margin:0; font-size:13px; word-break: break-all; }
.link-btn { background: transparent; color:#8de8ff; padding:0; border:0; }
.cluster-list { margin-top: 18px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
.cluster-chip { border:1px solid rgba(141,232,255,.24); border-radius:14px; padding:10px 12px; display:flex; gap:10px; }
.report-markdown { margin-top:18px; white-space:pre-wrap; background:#05070a; border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:16px; color:#dbeafe; max-height:420px; overflow:auto; }
.loading-state { padding: 80px; text-align:center; color:#96a3b8; }
.comparison-panel, .report-agent-panel {
  background: rgba(255,255,255,0.055);
  border: 1px solid rgba(251,191,36,0.22);
  border-radius: 18px;
  padding: 18px;
  box-shadow: 0 18px 45px rgba(0,0,0,.22);
}
.comparison-grid { display:grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap:14px; margin-top:16px; }
.pass-text { color:#86efac; }
.warn-text { color:#fde68a; }
.agent-context-grid { display:grid; grid-template-columns: 2fr 1fr 1fr; gap:14px; margin-top:16px; }
.suggested-question-list { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:12px; margin:16px 0; }
.suggested-question-card {
  text-align:left;
  border:1px solid rgba(141,232,255,.24);
  border-radius:16px;
  background:rgba(141,232,255,.08);
  color:#f4f7fb;
  padding:14px;
  cursor:pointer;
}
.suggested-question-card strong { display:block; margin:8px 0; line-height:1.35; }
.suggested-question-card small { display:block; color:#96a3b8; line-height:1.4; }
.question-label { display:inline-block; color:#8de8ff; font-size:12px; font-weight:700; letter-spacing:.04em; }
.ghost-btn.small { padding:8px 12px; font-size:12px; }
.agent-input-row { display:flex; gap:10px; }
.agent-input-row input { flex:1; border-radius:999px; border:1px solid rgba(141,232,255,.3); background:#05070a; color:#f4f7fb; padding:12px 14px; }
.agent-answer { margin-top:14px; white-space:pre-wrap; background:#05070a; border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:16px; color:#dbeafe; }

@media (max-width: 760px) {
  .mv-header, .control-panel, .report-header { flex-direction: column; align-items: flex-start; }
  .summary-grid, .aggregate-grid, .comparison-grid, .agent-context-grid { grid-template-columns: 1fr 1fr; }
}
</style>
