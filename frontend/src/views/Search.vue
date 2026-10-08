<template>
  <div class="search-page">
    <div class="mode-switch">
      <button :class="{ active: mode === 'local' }" @click="mode = 'local'">📚 库内检索</button>
      <button :class="{ active: mode === 'live' }" @click="mode = 'live'">🌐 全网实时</button>
      <span class="mode-hint" v-if="mode === 'local'">只搜已入库新闻（RAG 知识库）</span>
      <span class="mode-hint" v-else>联网抓最近 3 天全网新闻（Tavily，不入库）</span>
    </div>
    <div class="search-bar">
      <select v-if="mode === 'local'" v-model="category" class="cat-select">
        <option value="">全部模块</option>
        <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
      </select>
      <input
        v-model="query"
        @keyup.enter="doSearch"
        placeholder="输入自然语言查询，如：半导体板块、AI 芯片、黄金价格…"
      />
      <button @click="doSearch" :disabled="loading || !query.trim()">搜索</button>
    </div>

    <div v-if="!searched && mode === 'live' && hot.length" class="hot-section">
      <div class="hot-head">
        <span class="hot-fire">🔥 实时热点</span>
        <div class="hot-tabs">
          <button :class="{ active: hotTab === 'general' }" @click="switchHot('general')">综合热榜</button>
          <button :class="{ active: hotTab === 'tech' }" @click="switchHot('tech')">科技热榜</button>
          <button :class="{ active: hotTab === 'finance' }" @click="switchHot('finance')">财经热榜</button>
          <button :class="{ active: hotTab === 'intl' }" @click="switchHot('intl')">国际热榜</button>
        </div>
        <span class="hot-sub">{{ hotSub }}</span>
      </div>
      <div class="hot-list">
        <div v-for="(h, i) in hot" :key="h.url + i" class="hot-item" @click="searchHot(h)">
          <span class="hot-rank" :class="{ top3: i < 3 }">{{ i + 1 }}</span>
          <div class="hot-body">
            <div class="hot-text">{{ h.title }}</div>
            <div class="hot-meta">
              <span v-if="h.hotvalue" class="hot-value">🔥 {{ fmtHot(h.hotvalue) }}</span>
              <span>{{ h.source }}</span>
              <span>· {{ h.published_at }}</span>
            </div>
          </div>
          <div class="hot-actions" @click.stop>
            <button class="hot-act" @click="searchHot(h)">🔍 检索</button>
            <button class="hot-act hot-act-ai" @click="askAi(h)">🤖 问AI</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!searched && mode === 'local' && latest.length" class="latest-section">
      <div class="hot-head">
        <span class="hot-fire">📚 最新入库新闻</span>
        <span class="hot-sub">共 {{ latest.length }} 条 · 实时更新</span>
      </div>
      <div class="hot-list">
        <div v-for="(n, i) in latest" :key="n.id" class="hot-item" @click="query = n.title; doSearch()">
          <span class="hot-rank" :class="{ top3: i < 3 }">{{ i + 1 }}</span>
          <div class="hot-body">
            <div class="hot-text">{{ n.title }}</div>
            <div class="hot-meta">
              <span class="r-cat">{{ n.category }}</span>
              <span>{{ n.source }}</span>
              <span>· {{ n.published_at }}</span>
            </div>
          </div>
          <div class="hot-actions" @click.stop>
            <button class="hot-act" @click="query = n.title; doSearch()">🔍 检索</button>
            <button class="hot-act hot-act-ai" @click="router.push({ path: '/chat', query: { q: n.title } })">🤖 问AI</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="searched" class="back-bar">
      <button class="back-btn" @click="backToList">← 返回列表</button>
    </div>

    <div v-if="loading" class="hint">检索中…（向量 + BM25 + 时间加权）</div>
    <div v-else-if="error" class="hint error">{{ error }}</div>
    <div v-else-if="results.length" class="results">
      <div v-for="(d, i) in results" :key="d.id + '-' + d.url" class="result-card">
        <a v-if="d.url && d.url.startsWith('http')" :href="d.url" target="_blank" rel="noopener" class="r-title">{{ d.title }}</a><span v-else class="r-title">{{ d.title }}</span>
        <div class="r-meta">
          <span class="r-cat">{{ d.category }}</span>
          <span>{{ d.source }}</span>
          <span>· {{ d.published_at }}</span>
          <span class="r-score">相关度 {{ (d.score * 100).toFixed(1) }}%</span>
          <span class="r-trust" :class="'lv' + d.trust_level">可信度 {{ d.trust_level }}/5</span>
        </div>
        <p class="r-snippet">{{ d.snippet }}</p>
      </div>
    </div>
    <div v-else-if="searched" class="hint">未检索到相关新闻，换个问法试试。</div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ACTIVE_CATEGORIES, api } from '../api'

const router = useRouter()
// 模块下拉动态化：只显示库里有数据的模块
const categories = ref([])
const query = ref('')
const category = ref('')
const mode = ref('local') // local = 库内检索 / live = 全网实时
const results = ref([])
const loading = ref(false)
const error = ref('')
const searched = ref(false)
const hot = ref([]) // 实时热点榜
const hotTab = ref('general') // general 综合 / tech 科技 / finance 财经 / intl 国际
const hotSubMap = {
  general: '今日头条热榜 · 10 分钟更新',
  tech: '科技源最新新闻 · 10 分钟更新',
  finance: '库内财经最新 · 与库同步',
  intl: '库内国际最新 · 与库同步',
}
const hotSub = computed(() => hotSubMap[hotTab.value] || '')

async function loadHot(type = 'general') {
  hotTab.value = type
  try {
    hot.value = await api.get(`/api/news/hot?type=${type}`)
  } catch (e) {
    console.error(e)
  }
}

function switchHot(type) {
  if (type !== hotTab.value) loadHot(type)
}

// 热度格式化：23435853 → 2343.6万
function fmtHot(v) {
  if (!v) return ''
  if (v >= 100000000) return (v / 100000000).toFixed(1) + '亿'
  if (v >= 10000) return (v / 10000).toFixed(1) + '万'
  return String(v)
}

const latest = ref([])

async function loadLatest() {
  try {
    latest.value = await api.get('/api/news?page=1&size=15')
  } catch (e) {
    console.error(e)
  }
}

watch(mode, (m) => {
  // 切模式时重置搜索状态，显示默认内容
  searched.value = false
  results.value = []
  query.value = ''
  if (m === 'local') loadLatest()
  else loadHot(hotTab.value)
})

onMounted(async () => {
  if (mode.value === 'local') loadLatest()
  else loadHot('general')
  try {
    const s = await api.get('/api/news/stats')
    categories.value = Object.keys(s.by_category || {}).filter((c) => ACTIVE_CATEGORIES.includes(c)).sort()
  } catch (e) {
    /* 忽略 */
  }
})

async function doSearch() {
  const q = query.value.trim()
  if (!q || loading.value) return
  loading.value = true
  error.value = ''
  searched.value = true
  try {
    if (mode.value === 'live') {
      results.value = await api.post('/api/search/live', { query: q, top_k: 8 })
    } else {
      results.value = await api.post('/api/search', { query: q, top_k: 8, category: category.value })
    }
  } catch (e) {
    error.value = `请求失败：${e.message}`
    results.value = []
  } finally {
    loading.value = false
  }
}

// 返回列表
function backToList() {
  searched.value = false
  results.value = []
  query.value = ''
  if (mode.value === 'local') loadLatest()
  else loadHot(hotTab.value)
}

// 热榜联动：点击热搜词 → 全网实时搜索（热点新闻库里没有）
function searchHot(h) {
  query.value = h.title
  category.value = ''
  mode.value = 'live'
  doSearch()
}

// 热榜联动：问 AI → 跳转对话页并自动发问
function askAi(h) {
  router.push({ path: '/chat', query: { q: h.title } })
}
</script>

<style scoped>
.search-page { max-width: 760px; margin: 0 auto; }
.mode-switch { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
.mode-switch button {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all .2s;
}
.mode-switch button:hover { color: var(--primary); border-color: var(--primary); background: var(--primary-50); }
.mode-switch button.active {
  background: var(--primary-grad);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(43,110,243,.26);
}
.mode-hint { font-size: 12px; color: var(--text-mute); }
.search-bar {
  display: flex;
  gap: 8px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 6px;
  box-shadow: var(--shadow-sm);
  transition: border .2s, box-shadow .2s;
}
.search-bar:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(43,110,243,.10), var(--shadow); }
.cat-select {
  border: none;
  border-radius: var(--radius-sm);
  padding: 0 10px;
  font-size: 12px;
  background: var(--bg-soft);
  color: var(--text);
  min-width: 108px;
  outline: none;
}
.search-bar input {
  flex: 1;
  border: none;
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: 13px;
  outline: none;
  background: transparent;
}
.search-bar button {
  border: none;
  background: var(--primary-grad);
  color: #fff;
  border-radius: 8px;
  padding: 0 20px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity .2s, transform .1s;
}
.search-bar button:disabled { opacity: .5; }
.search-bar button:not(:disabled):active { transform: scale(.97); }

.hint { text-align: center; color: var(--text-mute); margin-top: 44px; font-size: 14px; }
.hint.error { color: var(--accent-red); }

/* ===== 实时热点榜（抖音热搜风） ===== */
.hot-section { margin-top: 16px; }
.hot-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.hot-fire { font-size: 15px; font-weight: 800; color: #0f172a; }
.hot-tabs {
  display: flex;
  gap: 4px;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px;
}
.hot-tabs button {
  border: none;
  background: transparent;
  border-radius: 999px;
  padding: 4px 14px;
  font-size: 12.5px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all .18s;
}
.hot-tabs button:hover { color: var(--primary); }
.hot-tabs button.active {
  background: var(--primary-grad);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(43,110,243,.25);
}
.hot-sub { font-size: 12px; color: var(--text-mute); margin-left: auto; }
.hot-list {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.hot-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  cursor: pointer;
  color: var(--text);
  border-bottom: 1px solid var(--border);
  transition: background .15s;
}
.hot-item:last-child { border-bottom: none; }
.hot-item:hover { background: var(--primary-50); }
.hot-actions { display: flex; gap: 6px; margin-left: auto; flex-shrink: 0; }
.hot-act {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all .15s;
  white-space: nowrap;
}
.hot-act:hover { color: var(--primary); border-color: var(--primary); background: #fff; }
.hot-act-ai { background: var(--primary-50); border-color: var(--primary-light); color: var(--primary-darker); }
.hot-act-ai:hover { background: var(--primary-grad); color: #fff; border-color: transparent; }
.hot-rank {
  font-size: 15px;
  font-weight: 800;
  width: 26px;
  text-align: center;
  color: #b3bcc9;
  flex-shrink: 0;
  font-style: italic;
}
.hot-rank.top3 {
  background: linear-gradient(135deg, #f97316, #ef4444);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hot-body { min-width: 0; }
.hot-text {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hot-item:hover .hot-text { color: var(--primary); }
.hot-meta { font-size: 12px; color: var(--text-mute); margin-top: 2px; }
.hot-value { color: #ef4444; font-weight: 700; }

.back-bar { margin-top: 12px; margin-bottom: 4px; }
.back-btn {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: 999px;
  padding: 5px 14px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all .15s;
}
.back-btn:hover { color: var(--primary); border-color: var(--primary); background: var(--primary-50); }

.results { margin-top: 16px; display: flex; flex-direction: column; gap: 10px; }
.result-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 16px;
  transition: all .2s;
}
.result-card:hover { box-shadow: var(--shadow); border-color: var(--border-strong); transform: translateY(-1px); }
.r-title { font-size: 14px; font-weight: 700; color: var(--text); text-decoration: none; line-height: 1.5; }
.r-title:hover { color: var(--primary); }
.r-meta { margin-top: 8px; font-size: 12px; color: var(--text-sub); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.r-cat { background: var(--primary-50); color: var(--primary-darker); border-radius: 999px; padding: 1px 8px; font-size: 11px; }
.r-score { color: var(--primary-dark); font-weight: 600; }
.r-trust { padding: 1px 8px; border-radius: 999px; font-size: 11px; }
.r-trust.lv5 { background: #eafaf1; color: #1a7f4f; }
.r-trust.lv4 { background: var(--primary-50); color: var(--primary-darker); }
.r-trust.lv3 { background: #fff7e6; color: #b26a00; }
.r-snippet { margin-top: 8px; font-size: 13px; color: var(--text-sub); line-height: 1.65; }
</style>
