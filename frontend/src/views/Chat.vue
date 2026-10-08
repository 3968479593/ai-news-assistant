<template>
  <div class="chat-page">
    <!-- 左侧：历史会话栏 -->
    <aside class="history-panel">
      <button class="history-new" @click="newChat" :disabled="busy">➕ 新对话</button>
      <div class="history-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="history-item"
          :class="{ active: s.id === sessionId }"
          @click="switchSession(s.id)"
        >
          <div class="history-title">{{ s.title }}</div>
          <div class="history-meta">
            <span>{{ fmtTime(s.updated_ts) }}</span>
            <span>{{ s.message_count }} 条</span>
            <button class="history-del" @click.stop="deleteSession(s.id)" title="删除会话">🗑</button>
          </div>
        </div>
        <div v-if="!sessions.length" class="history-empty">还没有历史会话<br>聊几句就会出现在这里</div>
      </div>
    </aside>

    <!-- 右侧：对话区 -->
    <div class="chat-box">
      <div class="chat-top">
        <span class="mem-hint" :title="sessionId">🧠 本会话有记忆 · 可连续追问</span>
        <div class="top-actions">
          <button class="think-toggle" :class="{ on: deepThink }" @click="toggleThink" :title="deepThink ? '已开启：回答前先展示思考要点' : '已关闭：直接生成回答'">
            🧠 深度思考{{ deepThink ? ' · 开' : ' · 关' }}
          </button>
        </div>
      </div>
      <div class="chat-list" ref="listRef">
        <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
          <div class="msg-avatar">{{ m.role === 'user' ? '🧑' : '🤖' }}</div>
          <div class="msg-body">
            <!-- 深度思考面板（生成中自动展开，完成后可点击展开/收起） -->
            <div v-if="m.thinking" class="think-panel" :class="{ done: m._thinkingDone }">
              <div class="think-head" @click="toggleThinkPanel(m)">
                <span class="think-label">🧠 深度思考</span>
                <span class="think-status">{{ !m._thinkingDone ? '思考中…' : (m._thinkingOpen ? '收起 ▲' : '展开 ▼') }}</span>
              </div>
              <div v-show="m._thinkingOpen" class="think-body">{{ m.thinking }}</div>
            </div>
            <div class="msg-bubble" :class="{ streaming: loading && isLastAssistant(i) }">
              <div class="md-body" v-html="renderMd(m.content)"></div>
              <span v-if="loading && isLastAssistant(i)" class="type-cursor"></span>
              <div class="msg-tags" v-if="(m.route && m.route !== 'chat') || (m.category && m.category !== '综合')">
                <span class="route-tag" v-if="m.route && m.route !== 'chat'">{{ routeLabel(m.route) }}</span>
                <span class="cat-tag" v-if="m.category && m.category !== '综合'">{{ m.category }}</span>
              </div>
            </div>
            <div class="msg-actions">
              <button v-if="m.role === 'user'" class="act-btn" @click="recallMsg(i)" :disabled="busy" title="撤回这条消息及其后的对话">↩︎ 撤回</button>
              <template v-if="m.role === 'assistant'">
                <button class="act-btn" @click="copyMsg(m)" :title="m._copied ? '已复制' : '复制回答'">{{ m._copied ? '✅ 已复制' : '📋 复制' }}</button>
                <button class="act-btn" @click="regenerate" :disabled="busy" title="重新生成回答">🔄 重新生成</button>
              </template>
            </div>
            <details v-if="m.sources && m.sources.length" class="sources">
              <summary>参考来源（{{ m.sources.length }}）</summary>
              <div v-for="(s, j) in m.sources" :key="j" class="source-item">
                <a v-if="s.url && s.url.startsWith('http')" :href="s.url" target="_blank" rel="noopener">{{ s.title }}</a><span v-else>{{ s.title }}</span>
                <span class="source-meta">{{ s.source }} · {{ s.published_at }}</span>
              </div>
            </details>
            <details v-if="m.related && m.related.length" class="sources">
              <summary>📌 相关新闻（{{ m.related.length }}）</summary>
              <div v-for="(r, j) in m.related" :key="j" class="source-item">
                <a v-if="r.url && r.url.startsWith('http')" :href="r.url" target="_blank" rel="noopener">{{ r.title }}</a><span v-else>{{ r.title }}</span>
                <span class="source-meta">{{ r.source }} · {{ r.published_at }}</span>
              </div>
            </details>
            <details v-if="m.agent_trace && m.agent_trace.length" class="sources">
              <summary>🤖 Agent 执行轨迹</summary>
              <div v-for="(t, k) in m.agent_trace" :key="k" class="trace-item">{{ t }}</div>
            </details>
          </div>
        </div>
        <div v-if="loading && thinkingText" class="msg-row assistant">
          <div class="msg-avatar">🤖</div>
          <div class="msg-body">
            <div class="msg-bubble typing">{{ thinkingText }}</div>
          </div>
        </div>
      </div>

      <div class="quick" v-if="messages.length <= 1">
        <button v-for="q in quick" :key="q" @click="send(q)" :disabled="busy">{{ q }}</button>
      </div>

      <div class="input-row">
        <input
          v-model="input"
          @keyup.enter="send(input)"
          placeholder="输入问题，如：大模型最近有什么新进展？"
          :disabled="busy"
        />
        <button @click="busy ? stopGen() : send(input)" :disabled="!busy && !input.trim()" :class="{ stop: busy }">
          {{ loading ? '⏹ 停止' : '发送' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { api } from '../api'

marked.setOptions({ gfm: true, breaks: true })

const route = useRoute()

const WELCOME = {
  role: 'assistant',
  content: '你好，我是 AI 新闻助手 🤖\n\n我专注科技 / AI 领域新闻，可以问我：\n· 某话题的来龙去脉（如「大模型最近有什么新进展？」）\n· 最新消息（如「今天科技圈有什么大事？」）\n· 新闻总结与对比',
}

const messages = ref([{ ...WELCOME }])
const input = ref('')
const loading = ref(false)   // 请求进行中（检索/生成）
const thinkingText = ref('') // 流式状态提示（检索中/生成中），首字到达后隐藏
const listRef = ref(null)
const sessions = ref([])     // 历史会话列表（左侧栏）
let abortCtrl = null

// 深度思考开关：默认关（回答快），需要深度解读时手动开；localStorage 持久化
const THINK_KEY = 'news_chat_deep_think'
const deepThink = ref(localStorage.getItem(THINK_KEY) === 'on')
function toggleThink() {
  deepThink.value = !deepThink.value
  localStorage.setItem(THINK_KEY, deepThink.value ? 'on' : 'off')
}

// 会话记忆：localStorage 持久化 session_id + 对话内容，切页面 / 刷新浏览器都不丢
const SESSION_KEY = 'news_chat_session'
const MSG_KEY = 'news_chat_messages'
const sessionId = ref(localStorage.getItem(SESSION_KEY) || '')

try {
  const saved = localStorage.getItem(MSG_KEY)
  if (saved) {
    const parsed = JSON.parse(saved)
    if (Array.isArray(parsed) && parsed.length) messages.value = parsed
  }
} catch { /* 损坏数据忽略 */ }

const busy = computed(() => loading.value)

// ---------------- 历史会话管理 ----------------

async function loadSessions() {
  try {
    const r = await api.get('/api/chat/history')
    sessions.value = r.sessions || []
  } catch (e) { console.error(e) }
}

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const hhmm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (sameDay) return hhmm
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return '昨天'
  return `${d.getMonth() + 1}-${d.getDate()}`
}

async function switchSession(id) {
  if (busy.value || id === sessionId.value) return
  try {
    const r = await api.get(`/api/chat/history/${id}`)
    if (r.ok && Array.isArray(r.messages) && r.messages.length) {
      messages.value = r.messages
    } else {
      messages.value = [{ ...WELCOME }]
    }
    sessionId.value = id
    localStorage.setItem(SESSION_KEY, id)
    try { localStorage.setItem(MSG_KEY, JSON.stringify(messages.value)) } catch { /* 忽略 */ }
    await scrollBottom()
  } catch (e) {
    console.error(e)
  }
}

async function deleteSession(id) {
  if (busy.value) return
  try {
    await api.delete(`/api/chat/history/${id}`)
    if (id === sessionId.value) {
      sessionId.value = ''
      localStorage.removeItem(SESSION_KEY)
      messages.value = [{ ...WELCOME }]
      localStorage.removeItem(MSG_KEY)
    }
    await loadSessions()
  } catch (e) { console.error(e) }
}

// 保存当前会话到后端（覆盖写，保证撤回/重生成后历史一致）
async function saveCurrent() {
  if (!sessionId.value) return
  try {
    await api.post(`/api/chat/history/${sessionId.value}`, { messages: messages.value })
  } catch (e) { console.error(e) }
}

function renderMd(text) {
  if (!text) return ''
  const html = marked.parse(text)
  return DOMPurify.sanitize(html)
}

async function newChat() {
  if (busy.value) return
  sessionId.value = ''
  localStorage.removeItem(SESSION_KEY)
  localStorage.removeItem(MSG_KEY)
  messages.value = [{ ...WELCOME }]
  await loadSessions()  // 刷新高亮（当前会话不在列表）
  await scrollBottom()
}

const quick = [
  '大模型最近有什么新进展？',
  '今天科技圈有什么大事？',
  '半导体 / 芯片行业最新动态？',
]

function routeLabel(route) {
  return { rag: '📚 库内检索', live: '⚡ 实时抓取', chat: '💬 闲聊' }[route] || route
}

async function scrollBottom() {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
}

async function copyMsg(m) {
  try {
    await navigator.clipboard.writeText(m.content)
    m._copied = true
    setTimeout(() => { m._copied = false }, 1600)
  } catch { /* 剪贴板不可用 */ }
}

function isLastAssistant(i) {
  return i === messages.value.length - 1 && messages.value[i].role === 'assistant'
}

function toggleThinkPanel(m) {
  m._thinkingOpen = !m._thinkingOpen
}

// 停止生成：中断 SSE 流，保留已生成内容
function stopGen() {
  if (abortCtrl) {
    abortCtrl.abort()
    abortCtrl = null
  }
}

// 撤回消息：删除该条用户消息及其后的所有消息，并清空后端会话记忆与缓存
async function recallMsg(i) {
  if (busy.value) return
  const m = messages.value[i]
  if (!m || m.role !== 'user') return
  messages.value.splice(i)
  try { localStorage.setItem(MSG_KEY, JSON.stringify(messages.value)) } catch { /* 忽略 */ }
  if (sessionId.value) {
    try { await api.post('/api/chat/history/clear', { message: '', session_id: sessionId.value }) } catch (e) { console.error(e) }
  }
  await saveCurrent()
  await scrollBottom()
}

async function send(text) {
  const q = (text || '').trim()
  if (!q || busy.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: q })
  loading.value = true
  thinkingText.value = '正在检索新闻库…'
  await scrollBottom()

  const msg = { role: 'assistant', content: '', thinking: '', _thinkingOpen: true, _thinkingDone: false, sources: [], related: [], route: '', category: '', agent_trace: [] }
  messages.value.push(msg)
  let full = ''
  let final = null
  abortCtrl = new AbortController()
  try {
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: q, session_id: sessionId.value, deep_think: deepThink.value }),
      signal: abortCtrl.signal,
    })
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)
    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const raw = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        handleEvent(raw, msg, (p) => { full += p.text || ''; msg.content = full }, (p) => { final = p })
      }
    }
    // 处理 buf 里残留的所有事件
    while (buf.trim()) {
      const idx = buf.indexOf('\n\n')
      const raw = idx >= 0 ? buf.slice(0, idx) : buf
      buf = idx >= 0 ? buf.slice(idx + 2) : ''
      if (!raw.trim()) break
      handleEvent(raw, msg, (p) => { full += p.text || ''; msg.content = full }, (p) => { final = p })
    }
    if (final) {
      msg.content = final.answer ?? full
      msg.sources = final.sources || []
      msg.related = final.related || []
      msg.route = final.route || ''
      msg.category = final.category || ''
      msg.agent_trace = final.agent_trace || []
      if (final.session_id) {
        sessionId.value = final.session_id
        localStorage.setItem(SESSION_KEY, final.session_id)
      }
    }
    await scrollBottom()
  } catch (e) {
    if (e.name === 'AbortError') {
      msg.content = full || '（已停止生成）'
    } else {
      msg.content = `请求失败：${e.message}`
    }
  } finally {
    loading.value = false
    thinkingText.value = ''
    abortCtrl = null
    if (msg.thinking && !msg._thinkingDone) msg._thinkingDone = true
    msg._thinkingOpen = false
    await scrollBottom()
    try { localStorage.setItem(MSG_KEY, JSON.stringify(messages.value)) } catch { /* 超限忽略 */ }
    // 持久化会话 + 刷新左侧历史栏
    await saveCurrent()
    await loadSessions()
  }
}

// 统一 SSE 事件分发（供 send 主循环与残留缓冲共用）
function handleEvent(raw, msg, onDelta, onDone) {
  const evt = (raw.match(/^event:\s*(.+)$/m) || [])[1]?.trim() || ''
  const data = (raw.match(/^data:\s*(.+)$/m) || [])[1]?.trim()
  if (!data) return
  let payload
  try { payload = JSON.parse(data) } catch (e) { console.warn('SSE parse fail:', evt, data.slice(0, 100)); return }
  if (evt === 'status') {
    if (payload.stage === 'retrieving') thinkingText.value = payload.detail || '正在检索…'
    else if (payload.stage === 'writing') thinkingText.value = ''
  } else if (evt === 'thinking_start') {
    thinkingText.value = ''
    msg.thinking = ''
    msg._thinkingOpen = true
    msg._thinkingDone = false
  } else if (evt === 'thinking_delta') {
    msg.thinking += payload.text || ''
    scrollBottom()
  } else if (evt === 'thinking_end') {
    msg._thinkingDone = true
    msg._thinkingOpen = false
  } else if (evt === 'delta') {
    thinkingText.value = ''
    onDelta(payload)
    scrollBottom()
  } else if (evt === 'error') {
    thinkingText.value = ''
    msg.content = `请求出错了：${payload.detail || '未知错误'}，请重试`
  } else if (evt === 'done') {
    onDone(payload)
  }
}

// 重新生成：删除最后一条用户消息及其后的全部回复，再重发该问题（避免 user 消息重复）
async function regenerate() {
  if (busy.value) return
  const lastUserIdx = [...messages.value].map((m) => m.role).lastIndexOf('user')
  if (lastUserIdx < 0) return
  const q = messages.value[lastUserIdx].content
  messages.value.splice(lastUserIdx)  // 删掉该条 user 及之后所有，send 会重新 push
  await send(q)
}

// 从检索页热榜"问AI"跳转而来：自动发起提问
onMounted(async () => {
  await loadSessions()
  // 有当前会话：优先从后端恢复完整历史（失败用本地缓存兜底）
  if (sessionId.value) {
    try {
      const r = await api.get(`/api/chat/history/${sessionId.value}`)
      if (r.ok && Array.isArray(r.messages) && r.messages.length) {
        messages.value = r.messages
      }
    } catch (e) { console.error(e) }
  }
  const q = route.query.q
  if (q && typeof q === 'string' && q.trim() && !busy.value) {
    setTimeout(() => send(q.trim()), 100)
  }
})
</script>

<style scoped>
.chat-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
  flex: 1;
  display: flex;
  gap: 16px;
  min-height: 0;
  overflow: hidden;
}
/* 左侧历史栏 */
.history-panel {
  width: 252px;
  flex-shrink: 0;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.history-new {
  margin: 12px;
  border: 1px solid var(--primary-light);
  background: var(--primary-50);
  color: var(--primary-dark);
  border-radius: 10px;
  padding: 9px 0;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all .2s;
}
.history-new:hover { background: var(--primary-light); }
.history-new:disabled { opacity: .5; cursor: not-allowed; }
.history-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.history-item {
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 9px 10px;
  cursor: pointer;
  transition: all .15s;
}
.history-item:hover { background: var(--bg-soft); }
.history-item.active {
  background: var(--primary-50);
  border-color: var(--primary-light);
}
.history-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.history-item.active .history-title { color: var(--primary-darker); }
.history-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
  font-size: 11.5px;
  color: var(--text-mute);
}
.history-del {
  margin-left: auto;
  border: none;
  background: none;
  font-size: 12px;
  cursor: pointer;
  opacity: 0;
  transition: opacity .15s;
  padding: 0 2px;
}
.history-item:hover .history-del { opacity: .7; }
.history-del:hover { opacity: 1; }
.history-empty {
  padding: 30px 12px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-mute);
  line-height: 1.8;
}
.chat-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.chat-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-soft);
}
.top-actions { display: flex; align-items: center; gap: 8px; }
.mem-hint {
  font-size: 12px;
  color: var(--primary-darker);
  background: var(--primary-50);
  border: 1px solid var(--primary-light);
  padding: 4px 12px;
  border-radius: 999px;
}
.think-toggle {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: 999px;
  padding: 5px 14px;
  font-size: 12.5px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all .2s;
}
.think-toggle.on {
  color: #1a7f4f;
  border-color: #b7ebcf;
  background: #eafaf1;
  font-weight: 600;
}
.think-toggle:not(.on):hover { color: var(--primary); border-color: var(--primary); background: var(--primary-50); }
.new-chat {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: 999px;
  padding: 5px 16px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all .2s;
}
.new-chat:hover { color: var(--primary); border-color: var(--primary); background: var(--primary-50); }
.new-chat:disabled { opacity: .5; cursor: not-allowed; }
.chat-list {
  height: calc(100vh - 280px);
  overflow-y: auto;
  overflow-x: hidden;
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  background:
    radial-gradient(circle at 15% 0%, rgba(43,110,243,.03), transparent 40%),
    radial-gradient(circle at 90% 100%, rgba(22,163,74,.03), transparent 40%);
}
.msg-row { display: flex; gap: 10px; }
.msg-row.user { flex-direction: row-reverse; }
.msg-avatar {
  width: 34px; height: 34px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 17px;
  background: var(--primary-50);
  border: 1px solid var(--primary-light);
  flex-shrink: 0;
}
.msg-row.user .msg-avatar { background: #ecfdf5; border-color: #c9f0dd; }
.msg-body { max-width: 88%; }
.msg-row.user .msg-body { display: flex; flex-direction: column; align-items: flex-end; }
.msg-bubble {
  background: #f7f9fd;
  border: 1px solid var(--border);
  border-radius: 14px;
  border-top-left-radius: 4px;
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}
.msg-row.user .msg-bubble {
  background: var(--primary-grad);
  color: #fff;
  border: none;
  border-radius: 14px;
  border-top-right-radius: 4px;
  box-shadow: 0 4px 12px rgba(43,110,243,.18);
}
.msg-row.user .msg-bubble .md-body { color: #fff; }

/* 深度思考面板 */
.think-panel {
  background: #f3f5f9;
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 8px;
  overflow: hidden;
}
.think-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 12px;
  cursor: pointer;
  user-select: none;
}
.think-label { font-size: 12.5px; font-weight: 600; color: var(--text-sub); }
.think-status { font-size: 11.5px; color: var(--text-mute); }
.think-body {
  padding: 0 12px 10px;
  font-size: 12.5px;
  color: var(--text-sub);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px dashed var(--border);
  padding-top: 8px;
  margin: 0 12px 10px;
}
.think-panel.done .think-body { border-top: 1px dashed var(--border); }

/* markdown 内容样式 */
.md-body :deep(p) { margin: 0 0 8px; }
.md-body :deep(p:last-child) { margin-bottom: 0; }
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3), .md-body :deep(h4) {
  margin: 12px 0 6px; font-weight: 700; line-height: 1.4;
}
.md-body :deep(h1) { font-size: 1.25em; }
.md-body :deep(h2) { font-size: 1.15em; }
.md-body :deep(h3) { font-size: 1.05em; }
.md-body :deep(h4) { font-size: 1em; }
.md-body :deep(ul), .md-body :deep(ol) { margin: 0 0 8px; padding-left: 22px; }
.md-body :deep(li) { margin: 3px 0; }
.md-body :deep(strong) { font-weight: 700; }
.md-body :deep(code) {
  background: rgba(0,0,0,.06);
  border-radius: 4px;
  padding: 1px 6px;
  font-family: Consolas, Monaco, monospace;
  font-size: .9em;
}
.msg-row.user .md-body :deep(code) { background: rgba(255,255,255,.18); }
.md-body :deep(pre) {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0;
  font-size: 13px;
  line-height: 1.6;
}
.md-body :deep(pre code) { background: none; padding: 0; color: inherit; }
.md-body :deep(blockquote) {
  border-left: 3px solid var(--primary-light);
  padding-left: 12px;
  color: var(--text-sub);
  margin: 8px 0;
}
.md-body :deep(a) { color: var(--primary); }
.msg-row.user .md-body :deep(a) { color: #dff3ff; }
.md-body :deep(table) { border-collapse: collapse; margin: 8px 0; width: 100%; }
.md-body :deep(th), .md-body :deep(td) { border: 1px solid var(--border); padding: 6px 10px; text-align: left; font-size: 13px; }
.md-body :deep(th) { background: var(--bg-soft); font-weight: 600; }
.md-body :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 10px 0; }

.msg-actions {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}
.act-btn {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all .2s;
}
.act-btn:hover { color: var(--primary); border-color: var(--primary); background: var(--primary-50); }
.act-btn:disabled { opacity: .5; cursor: not-allowed; }

.route-tag {
  margin-top: 8px;
  font-size: 12px;
  color: var(--primary-darker);
  background: var(--primary-50);
  border: 1px solid var(--primary-light);
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
}
.cat-tag {
  margin-top: 8px;
  margin-left: 6px;
  font-size: 12px;
  color: #1a7f4f;
  background: #eafaf1;
  border: 1px solid #b7ebcf;
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
}
.typing { color: var(--text-mute); }
.type-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  background: var(--primary);
  vertical-align: text-bottom;
  margin-left: 2px;
  animation: blink 0.8s steps(1) infinite;
}
@keyframes blink { 50% { opacity: 0; } }
.sources {
  margin-top: 8px;
  font-size: 12px;
}
.sources summary {
  cursor: pointer;
  color: var(--primary-dark);
  user-select: none;
}
.source-item {
  padding: 6px 0;
  border-bottom: 1px dashed var(--border);
}
.source-item a { color: var(--text); text-decoration: none; }
.source-item a:hover { color: var(--primary); }
.source-meta { display: block; color: var(--text-mute); font-size: 12px; margin-top: 2px; }
.trace-item {
  padding: 3px 0;
  color: var(--text-sub);
  font-size: 12px;
  line-height: 1.6;
}

.quick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  background: var(--bg-soft);
}
.quick button {
  border: 1px solid var(--border-strong);
  background: var(--card);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all .2s;
}
.quick button:hover { color: var(--primary); border-color: var(--primary); background: var(--primary-50); }

.input-row {
  display: flex;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--border);
  background: var(--bg-soft);
}
.input-row input {
  flex: 1;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  padding: 11px 16px;
  font-size: 14px;
  outline: none;
  background: var(--card);
  transition: border .2s, box-shadow .2s;
}
.input-row input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(43,110,243,.12); }
.input-row button {
  border: none;
  background: var(--primary-grad);
  color: #fff;
  border-radius: var(--radius);
  padding: 10px 28px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity .2s, transform .1s;
}
.input-row button:disabled { opacity: .5; cursor: not-allowed; }
.input-row button:not(:disabled):active { transform: scale(.97); }
.input-row button.stop { background: #dc2626; }
</style>
