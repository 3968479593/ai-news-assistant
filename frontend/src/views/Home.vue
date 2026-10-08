<template>
  <div class="home">
    <section class="hero">
      <div class="hero-deco hero-deco-a"></div>
      <div class="hero-deco hero-deco-b"></div>
      <p class="hero-kicker">智能新闻问答 · 本地 RAG</p>
      <h2>基于 LangGraph 的新闻知识助手</h2>
      <p class="hero-sub">向量 + BM25 混合检索 · 时间衰减加权 · 实时抓取 · 带引用回答</p>
      <div class="hero-stats" v-if="stats">
        <div class="stat">
          <b>{{ stats.total }}</b>
          <span>新闻总数</span>
        </div>
        <div class="stat" v-for="row in categoryRows" :key="row.name">
          <b>{{ row.count }}</b>
          <span>{{ row.name }}</span>
        </div>
      </div>
    </section>

    <section class="cards">
      <router-link to="/chat" class="card">
        <span class="card-ico card-ico-blue">💬</span>
        <h3>AI 对话</h3>
        <p>问新闻来龙去脉、最新消息，回答带引用来源</p>
        <span class="card-go">开始对话 →</span>
      </router-link>
      <router-link to="/search" class="card">
        <span class="card-ico card-ico-green">🔍</span>
        <h3>新闻检索</h3>
        <p>自然语言检索新闻库，按相关度 + 时效排序</p>
        <span class="card-go">去检索 →</span>
      </router-link>
      <router-link to="/news" class="card">
        <span class="card-ico card-ico-orange">📰</span>
        <h3>新闻库</h3>
        <p>浏览已入库新闻，支持按来源筛选与手动刷新</p>
        <span class="card-go">浏览新闻库 →</span>
      </router-link>
    </section>

    <section class="pipeline">
      <div class="pipeline-head">
        <h3>技术架构</h3>
        <span class="pipeline-tag">RSS / Tavily → RAG → Agent</span>
      </div>
      <div class="pipe">
        <span>RSS / Tavily</span><i>→</i>
        <span>清洗入库</span><i>→</i>
        <span>BGE-M3 嵌入</span><i>→</i>
        <span>Chroma 向量库</span><i>→</i>
        <span>LangGraph Agent</span><i>→</i>
        <span>带引用回答</span>
      </div>
    </section>

    <section class="pipeline">
      <div class="pipeline-head">
        <h3>系统评测 · RAG 质量</h3>
        <div class="eval-actions">
          <span class="pipeline-tag">{{ evalData ? evalData.n + ' 条真实问题 · DeepSeek judge · ' + evalTime : '尚未评测' }}</span>
          <button class="eval-run" :disabled="evalRunning" @click="runEval">
            {{ evalRunning ? '评测中…' : '▶ 运行评测' }}
          </button>
        </div>
      </div>

      <!-- 运行中：进度 -->
      <div v-if="evalRunning" class="eval-progress">
        <div class="eval-bar"><i :style="{ width: evalPct + '%' }"></i></div>
        <p>{{ evalCurrent }}/{{ evalTotal }} · {{ evalQuestion }}</p>
      </div>

      <!-- 有结果：指标卡 + 明细 -->
      <template v-if="evalData">
        <div class="eval-grid">
          <div class="eval-card">
            <b class="eval-score eval-good">{{ fmt(evalData.summary.avg_faithfulness) }}</b>
            <span>忠实度 Faithfulness</span>
            <small>回答被上下文支持的比例，越高越不编造</small>
          </div>
          <div class="eval-card">
            <b class="eval-score eval-good">{{ fmt(evalData.summary.avg_answer_relevancy) }}</b>
            <span>答案相关性 Relevancy</span>
            <small>回答切题程度，满分 1.0</small>
          </div>
          <div class="eval-card">
            <b class="eval-score">{{ fmt(evalData.summary.avg_context_precision) }}</b>
            <span>上下文精确率 AP@5</span>
            <small>检索候选集中直接相关的占比（受库容量制约）</small>
          </div>
          <div class="eval-card eval-hit">
            <b class="eval-score eval-good">{{ fmt(evalData.top1_hit_rate) }}</b>
            <span>top1 命中率</span>
            <small>最相关新闻排在第一位的比例</small>
          </div>
        </div>
        <table class="eval-table">
          <thead><tr><th>#</th><th>问题</th><th>模块</th><th>AP@5</th><th>Faith</th><th>Rel</th><th>top1</th></tr></thead>
          <tbody>
            <tr v-for="(it, i) in evalData.items" :key="i">
              <td>{{ i + 1 }}</td>
              <td class="eval-q">{{ it.question }}</td>
              <td>{{ it.category }}</td>
              <td>{{ it.context_precision.toFixed(2) }}</td>
              <td>{{ it.faithfulness.toFixed(2) }}</td>
              <td>{{ it.answer_relevancy.toFixed(2) }}</td>
              <td>{{ it.top1_hit ? '✅' : '❌' }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const stats = ref(null)
const health = ref(null)
const evalData = ref(null)
const evalRunning = ref(false)
const evalCurrent = ref(0)
const evalTotal = ref(0)
const evalQuestion = ref('')
let evalTimer = null

const evalPct = computed(() => evalTotal.value ? Math.round(evalCurrent.value / evalTotal.value * 100) : 0)

function fmt(v) { return Number(v || 0).toFixed(2) }

const evalTime = computed(() => {
  if (!evalData.value?.updated_at) return ''
  const d = new Date(evalData.value.updated_at * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

async function loadEval() {
  try { evalData.value = await api.get('/api/eval/report') } catch (e) { evalData.value = null }
}

function stopEvalPoll() {
  if (evalTimer) { clearInterval(evalTimer); evalTimer = null }
}

async function pollEval() {
  try {
    const s = await api.get('/api/eval/status')
    evalRunning.value = s.running
    evalCurrent.value = s.current || 0
    evalTotal.value = s.total || 0
    evalQuestion.value = s.question || ''
    if (!s.running) {
      stopEvalPoll()
      await loadEval()
    }
  } catch (e) { console.error(e) }
}

async function runEval() {
  try {
    await api.post('/api/eval/run')
    evalRunning.value = true
    evalTimer = setInterval(pollEval, 2000)
  } catch (e) {
    console.error(e)
  }
}

const categoryRows = computed(() => {
  if (!stats.value?.by_category) return []
  return Object.entries(stats.value.by_category)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([name, count]) => ({ name, count }))
})

onMounted(async () => {
  try { stats.value = await api.get('/api/news/stats') } catch (e) { console.error(e) }
  try { health.value = await api.get('/api/health') } catch (e) { console.error(e) }
  await loadEval()
  // 若已有评测在跑（页面刷新），恢复进度轮询
  try {
    const s = await api.get('/api/eval/status')
    if (s.running) {
      evalRunning.value = true
      evalTimer = setInterval(pollEval, 2000)
    }
  } catch (e) { console.error(e) }
})
</script>

<style scoped>
.hero {
  position: relative;
  overflow: hidden;
  background: linear-gradient(135deg, #0b2a6b 0%, #123b8f 48%, #1e55d0 100%);
  border-radius: var(--radius-lg);
  color: #fff;
  padding: 46px 36px 38px;
  text-align: center;
  box-shadow: 0 16px 40px rgba(18,59,143,.28);
}
.hero-deco { position: absolute; border-radius: 50%; pointer-events: none; }
.hero-deco-a {
  width: 340px; height: 340px;
  right: -120px; top: -160px;
  background: radial-gradient(circle, rgba(255,255,255,.14), transparent 65%);
}
.hero-deco-b {
  width: 260px; height: 260px;
  left: -90px; bottom: -140px;
  background: radial-gradient(circle, rgba(43,110,243,.55), transparent 65%);
}
.hero-kicker {
  position: relative;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 2px;
  color: #9fc0ff;
  text-transform: uppercase;
}
.hero h2 {
  position: relative;
  margin-top: 10px;
  font-size: 26px;
  font-weight: 800;
  letter-spacing: .5px;
}
.hero-sub {
  position: relative;
  margin-top: 10px;
  font-size: 13.5px;
  color: #b9ccf2;
}
.hero-stats {
  position: relative;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 26px;
}
.stat {
  background: rgba(255,255,255,.10);
  border: 1px solid rgba(255,255,255,.16);
  border-radius: var(--radius);
  padding: 12px 24px;
  min-width: 108px;
  backdrop-filter: blur(4px);
}
.stat b { display: block; font-size: 24px; font-weight: 800; }
.stat span { font-size: 12px; color: #b9ccf2; }

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 16px;
  margin-top: 22px;
}
.card {
  position: relative;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 26px 24px 22px;
  text-decoration: none;
  color: var(--text);
  transition: all .2s ease;
}
.card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
  border-color: transparent;
}
.card-ico {
  width: 46px; height: 46px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}
.card-ico-blue { background: var(--primary-50); }
.card-ico-green { background: #ecfdf5; }
.card-ico-orange { background: #fff4ea; }
.card h3 { margin-top: 14px; font-size: 17px; font-weight: 700; }
.card p { margin-top: 6px; color: var(--text-sub); font-size: 13px; line-height: 1.6; }
.card-go {
  display: inline-block;
  margin-top: 14px;
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
}

.pipeline {
  margin-top: 22px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 22px 24px;
}
.pipeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.pipeline h3 { font-size: 15px; font-weight: 700; }
.pipeline-tag { font-size: 12px; color: var(--text-mute); }
.pipe {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.pipe span {
  background: var(--primary-50);
  border: 1px solid var(--primary-light);
  color: var(--primary-darker);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
}
.pipe i { color: var(--text-mute); font-style: normal; }

.eval-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.eval-card {
  background: var(--primary-50);
  border: 1px solid var(--primary-light);
  border-radius: var(--radius);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.eval-hit { background: #ecfdf5; border-color: #a7f3d0; }
.eval-score { font-size: 30px; font-weight: 800; color: var(--text); }
.eval-score.eval-good { color: #059669; }
.eval-card span { font-size: 13px; font-weight: 600; color: var(--text); }
.eval-card small { font-size: 12px; color: var(--text-mute); line-height: 1.5; }
.eval-note { margin-top: 12px; font-size: 12px; color: var(--text-mute); }
.eval-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.eval-run {
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
  border-radius: 999px;
  padding: 5px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all .2s ease;
}
.eval-run:hover:not(:disabled) { background: var(--primary-dark); box-shadow: var(--shadow-md); }
.eval-run:disabled { opacity: .55; cursor: not-allowed; }
.eval-progress { margin: 12px 0 4px; }
.eval-bar {
  height: 8px;
  background: var(--primary-50);
  border: 1px solid var(--primary-light);
  border-radius: 999px;
  overflow: hidden;
}
.eval-bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--primary-light), var(--primary));
  border-radius: 999px;
  transition: width .6s ease;
}
.eval-progress p { margin-top: 8px; font-size: 12px; color: var(--text-sub); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.eval-table {
  width: 100%;
  margin-top: 14px;
  border-collapse: collapse;
  font-size: 12.5px;
}
.eval-table th, .eval-table td {
  border: 1px solid var(--border);
  padding: 6px 10px;
  text-align: left;
}
.eval-table th { background: var(--primary-50); font-weight: 600; color: var(--text); }
.eval-table td { color: var(--text-sub); }
.eval-q { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
