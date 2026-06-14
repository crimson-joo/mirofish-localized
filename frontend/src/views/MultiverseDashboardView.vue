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
          <button class="primary-btn" :disabled="busy" @click="prepareExperiment">Prepare Queue</button>
          <button class="primary-btn accent" :disabled="busy" @click="startExperiment">Run Queue</button>
          <button class="ghost-btn" :disabled="busy" @click="loadReport">Aggregate Report</button>
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
  getMultiverse,
  getMultiverseReport,
  getMultiverseStatus,
  prepareMultiverse,
  startMultiverse
} from '../api/simulation'

const route = useRoute()
const router = useRouter()
const multiverseId = computed(() => route.params.multiverseId)
const experiment = ref(null)
const aggregate = ref(null)
const reportMarkdown = ref('')
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
    const res = await getMultiverseReport(multiverseId.value)
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
    await prepareMultiverse(multiverseId.value, { use_llm_for_profiles: true })
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

const loadAll = async () => {
  await refreshStatus()
  await loadExperiment()
}

onMounted(async () => {
  await loadExperiment()
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
.summary-grid, .aggregate-grid { display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 14px; }
.summary-card, .control-panel, .universe-card, .report-panel {
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
@media (max-width: 760px) {
  .mv-header, .control-panel, .report-header { flex-direction: column; align-items: flex-start; }
  .summary-grid, .aggregate-grid { grid-template-columns: 1fr 1fr; }
}
</style>
