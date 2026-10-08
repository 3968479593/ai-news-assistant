<template>
  <div class="news-page">
    <div class="toolbar">
      <div class="toolbar-left">
        <span class="total" v-if="stats">共 <b>{{ stats.total }}</b> / {{ stats.max_items }} 条<span v-if="stats.retention_days"> · 保留 {{ stats.retention_days }} 天</span></span>
        <select v-model="category" @change="load(1)">
          <option value="">全部模块</option>
          <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="source" @change="load(1)">
          <option value="">全部来源</option>
          <option v-for="(c, s) in (stats?.by_source || {})" :key="s" :value="s">{{ s }}（{{ c }}）</option>
        </select>
      </div>
      <button class="refresh" @click="doRefresh" :disabled="refreshing">
        {{ refreshing ? '刷新中…' : '🔄 抓取最新新闻' }}
      </button>
    </div>

    <div class="filter-card">
      <div class="filter-head">
        <span class="filter-title">🎯 入库主题过滤</span>
        <span class="filter-tip">设置后，抓取/导入只收命中关键词的新闻（留空 = 全量收录）</span>
      </div>
      <div class="filter-row">
        <input
          v-model="filterInput"
          placeholder="如：AI, 芯片, 半导体, 大模型（逗号分隔，标题或正文命中即入库）"
          @keyup.enter="saveFilter"
        />
        <button class="filter-save" @click="saveFilter" :disabled="saving">
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <button v-if="filterInput.trim()" class="filter-clear" @click="clearFilter">清空（全收）</button>
      </div>
      <div v-if="filterMsg" class="filter-msg">{{ filterMsg }}</div>
    </div>

    <div v-if="refreshing" class="hint">{{ progressText }}</div>
    <div v-else-if="refreshMsg" class="hint ok">{{ refreshMsg }}</div>

    <div class="news-list" v-if="items.length">
      <div v-for="n in items" :key="n.id" class="news-item" :class="{ expanded: expandedId === n.id }" @click="toggleExpand(n.id)">
        <div class="n-title">
          <a v-if="n.url && n.url.startsWith('http')" :href="n.url" target="_blank" rel="noopener" @click.stop>{{ n.title }}</a><span v-else @click.stop>{{ n.title }}</span>
        </div>
        <div class="n-meta">
          <span class="n-cat">{{ n.category }}</span>
          <span>{{ n.source }}</span>
          <span>· {{ n.published_at }}</span>
          <span class="n-chunks">分块 {{ n.chunk_count }}</span>
          <span class="n-trust" :class="'lv' + n.trust_level">可信度 {{ n.trust_level }}/5</span>
        </div>
        <div v-if="expandedId === n.id && n.snippet" class="n-snippet">{{ n.snippet }}…</div>
        <div v-if="expandedId === n.id" class="n-actions">
          <a v-if="n.url && n.url.startsWith('http')" :href="n.url" target="_blank" rel="noopener" class="n-open">🔗 阅读原文</a>
        </div>
        <div class="n-expand">{{ expandedId === n.id ? '收起 ▲' : '展开摘要 ▼' }}</div>
      </div>
    </div>
    <div v-else-if="!loading" class="hint">暂无新闻，点击右上角「抓取最新新闻」或先运行 scripts/offline_ingest.py 导入。</div>

    <div class="pager" v-if="totalPages > 1">
      <button :disabled="page <= 1" @click="load(page - 1)">上一页</button>
      <span>{{ page }} / {{ totalPages }}</span>
      <button :disabled="page >= totalPages" @click="load(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ACTIVE_CATEGORIES, api } from '../api'

const items = ref([])
const stats = ref(null)
const expandedId = ref(null)  // 当前展开摘要的新闻 id（点击卡片切换）
function toggleExpand(id) {
  expandedId.value = expandedId.value === id ? null : id
}
// 模块下拉动态化：只显示库里有数据的模块（与 stats.by_category 对齐）
const categories = computed(() => {
  if (!stats.value?.by_category) return []
  return Object.keys(stats.value.by_category).filter((c) => ACTIVE_CATEGORIES.includes(c)).sort()
})
const source = ref('')
const category = ref('')
const page = ref(1)
const size = 20
const loading = ref(false)
const refreshing = ref(false)
const refreshMsg = ref('')
const progressText = ref('')
let progressTimer = null
const filterInput = ref('')
const saving = ref(false)
const filterMsg = ref('')

async function loadFilter() {
  try {
    const r = await api.get('/api/settings/ingest-filter')
    filterInput.value = (r.keywords || []).join(', ')
  } catch (e) {
    /* 忽略 */
  }
}

async function saveFilter() {
  saving.value = true
  filterMsg.value = ''
  try {
    const kws = filterInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
    const r = await api.put('/api/settings/ingest-filter', { keywords: kws })
    filterMsg.value = r.keywords.length ? `✅ 已保存，之后抓取只收：${r.keywords.join(' / ')}` : '✅ 已清空，恢复全量收录'
  } catch (e) {
    filterMsg.value = `保存失败：${e.message}`
  } finally {
    saving.value = false
  }
}

async function clearFilter() {
  filterInput.value = ''
  await saveFilter()
}

const filteredTotal = ref(0)
const totalPages = computed(() => Math.max(1, Math.ceil((filteredTotal.value || stats.value?.total || 0) / size)))

async function load(p = 1) {
  loading.value = true
  page.value = p
  try {
    const params = new URLSearchParams({ page: p, size, with_total: 1 })
    if (source.value) params.set('source', source.value)
    if (category.value) params.set('category', category.value)
    const r = await api.get(`/api/news?${params}`)
    // 空页自愈：筛选/跳页落到无数据页时回退到最后一页，不展示空页
    if (r.items.length === 0 && p > 1) {
      page.value = p - 1
      return load(p - 1)
    }
    items.value = r.items
    filteredTotal.value = r.total
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try { stats.value = await api.get('/api/news/stats') } catch (e) { console.error(e) }
}

function stopProgressPoll() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
}

async function pollProgress() {
  try {
    const s = await api.get('/api/news/refresh/status')
    const p = s.progress || {}
    const stage = p.stage || ''
    if (stage === 'fetching') progressText.value = '⏳ 正在抓取新闻源…（约 10-20 秒）'
    else if (stage === 'ingesting') progressText.value = `⏳ 已抓取 ${p.total || 0} 条，正在入库 ${p.processed || 0} 条…（已过滤 ${p.filtered || 0} 条）`
    else if (stage === 'cleaning') progressText.value = '⏳ 正在清理过期 / 超限新闻…'
    else if (stage === 'error') progressText.value = `❌ 刷新失败：${p.detail || ''}`
    else progressText.value = '⏳ 刷新中…'
  } catch (e) {
    progressText.value = '⏳ 刷新中…'
  }
}

async function doRefresh() {
  refreshing.value = true
  refreshMsg.value = ''
  progressText.value = '⏳ 准备刷新…'
  progressTimer = setInterval(pollProgress, 2000)
  try {
    const r = await api.post('/api/news/refresh')
    const parts = [`新增 ${r.added} 条`, `过滤 ${r.filtered || 0} 条`, `跳过 ${r.skipped} 条`, `失败 ${r.failed} 条`]
    refreshMsg.value = `抓取完成：${parts.join('，')}`
    await loadStats()
    await load(1)
  } catch (e) {
    refreshMsg.value = `刷新失败：${e.message}`
  } finally {
    stopProgressPoll()
    refreshing.value = false
  }
}

onMounted(() => { loadStats(); load(1); loadFilter() })
</script>

<style scoped>
.news-page { max-width: 880px; margin: 0 auto; }

/* ===== 入库主题过滤卡片 ===== */
.filter-card {
  margin: 16px 0 20px;
  background: linear-gradient(135deg, #eef4ff, #fbf7ff);
  border: 1px solid #dde7fb;
  border-radius: 14px;
  padding: 16px 18px;
}
.filter-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.filter-title { font-size: 14px; font-weight: 800; color: #0f172a; }
.filter-tip { font-size: 12px; color: var(--text-mute); }
.filter-row { display: flex; gap: 8px; flex-wrap: wrap; }
.filter-row input {
  flex: 1;
  min-width: 260px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  font-size: 13px;
  background: var(--card);
  color: var(--text);
  outline: none;
  transition: border .2s, box-shadow .2s;
}
.filter-row input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(43,110,243,.10); }
.filter-save {
  border: none;
  background: var(--primary-grad);
  color: #fff;
  border-radius: var(--radius-sm);
  padding: 9px 20px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.filter-save:disabled { opacity: .6; }
.filter-clear {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: var(--radius-sm);
  padding: 9px 14px;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-sub);
  transition: all .2s;
}
.filter-clear:hover { color: var(--accent-red); border-color: #fecaca; background: #fef2f2; }
.filter-msg { margin-top: 8px; font-size: 12.5px; color: var(--accent-green); }

.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.toolbar-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.total { font-size: 14px; color: var(--text-sub); }
.total b { color: var(--primary-dark); }
.toolbar select {
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  font-size: 13px;
  background: var(--card);
  color: var(--text);
  outline: none;
  transition: border .2s;
}
.toolbar select:focus { border-color: var(--primary); }
.refresh {
  border: 1px solid var(--primary);
  color: var(--primary);
  background: var(--card);
  border-radius: var(--radius-sm);
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all .2s;
}
.refresh:hover { background: var(--primary-50); box-shadow: 0 2px 8px rgba(43,110,243,.14); }
.refresh:disabled { opacity: .5; }

.hint { text-align: center; color: var(--text-mute); margin: 40px 0; font-size: 14px; }
.hint.ok { color: var(--accent-green); }

.news-list { margin-top: 20px; display: flex; flex-direction: column; gap: 10px; }
.news-item {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 18px;
  transition: all .2s;
  cursor: pointer;
}
.news-item:hover { box-shadow: var(--shadow); border-color: var(--border-strong); transform: translateY(-1px); }
.news-item.expanded { border-color: var(--primary-light); background: linear-gradient(180deg, var(--primary-50), var(--card) 60%); }
.n-title a { font-size: 14px; font-weight: 600; color: var(--text); text-decoration: none; line-height: 1.5; }
.n-title a:hover { color: var(--primary); }
.n-meta { margin-top: 6px; font-size: 12px; color: var(--text-sub); display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.n-cat { background: var(--primary-50); color: var(--primary-darker); border-radius: 999px; padding: 1px 8px; font-size: 11px; }
.n-chunks { color: var(--text-mute); }
.n-trust { padding: 1px 8px; border-radius: 999px; font-size: 11px; }
.n-trust.lv5 { background: #eafaf1; color: #1a7f4f; }
.n-trust.lv4 { background: var(--primary-50); color: var(--primary-darker); }
.n-trust.lv3 { background: #fff7e6; color: #b26a00; }
.n-snippet {
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--card);
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-sub);
}
.n-actions { margin-top: 8px; }
.n-open {
  display: inline-block;
  border: 1px solid var(--primary-light);
  color: var(--primary-dark);
  background: var(--card);
  border-radius: 999px;
  padding: 4px 14px;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  transition: all .2s;
}
.n-open:hover { background: var(--primary); color: #fff; border-color: var(--primary); }
.n-expand { margin-top: 8px; font-size: 11.5px; color: var(--text-mute); }

.pager { display: flex; justify-content: center; align-items: center; gap: 14px; margin-top: 26px; }
.pager button {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: var(--radius-sm);
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  transition: all .2s;
}
.pager button:not(:disabled):hover { color: var(--primary); border-color: var(--primary); background: var(--primary-50); }
.pager button:disabled { opacity: .4; }
.pager span { font-size: 13px; color: var(--text-sub); }
</style>
