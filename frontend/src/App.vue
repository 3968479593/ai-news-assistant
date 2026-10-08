<template>
  <div class="app">
    <header class="header">
      <div class="header-inner">
        <router-link to="/" class="brand">
          <span class="brand-mark">N</span>
          <span class="brand-text">
            <strong>AI 新闻助手</strong>
            <small>科技 / AI 新闻 · LangGraph RAG 智能问答</small>
          </span>
        </router-link>
        <nav class="nav">
          <router-link to="/" class="nav-item" exact-active-class="active">
            首页
          </router-link>
          <router-link to="/chat" class="nav-item" active-class="active">
            AI 对话
          </router-link>
          <router-link to="/search" class="nav-item" active-class="active">
            新闻检索
          </router-link>
          <router-link to="/news" class="nav-item" active-class="active">
            新闻库
          </router-link>
        </nav>
      </div>
    </header>

    <main class="main">
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>
    </main>

    <footer class="footer">
      <span>AI 新闻助手 · 向量 + BM25 混合检索 · 时间加权 · 带引用回答</span>
    </footer>
  </div>
</template>

<script setup>
</script>

<style>
/* ===== 全局设计系统 ===== */
:root {
  --primary: #2b6ef3;
  --primary-dark: #1e55d0;
  --primary-darker: #16409f;
  --primary-light: #dbe7ff;
  --primary-50: #eef4ff;
  --accent-green: #16a34a;
  --accent-orange: #f97316;
  --accent-red: #ef4444;
  --bg: #f5f7fb;
  --bg-soft: #fafbfe;
  --text: #0f172a;
  --text-sub: #4b5563;
  --text-mute: #94a3b8;
  --card: #ffffff;
  --border: #e6eaf1;
  --border-strong: #d5dce7;
  --radius-sm: 8px;
  --radius: 12px;
  --radius-lg: 16px;
  --shadow-sm: 0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06);
  --shadow: 0 4px 16px rgba(15,23,42,.07);
  --shadow-lg: 0 14px 36px rgba(15,23,42,.12);
  --shadow-primary: 0 6px 18px rgba(43,110,243,.28);
  --primary-grad: linear-gradient(135deg, #2b6ef3 0%, #1e55d0 100%);
}

* { margin: 0; padding: 0; box-sizing: border-box; }
html, body {
  height: 100%;
  overflow: hidden;
  font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif;
  background: var(--bg);
  color: var(--text);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
#app { height: 100%; }
.app { height: 100%; display: flex; flex-direction: column; }

/* ===== 顶栏 ===== */
.header {
  background: rgba(255,255,255,.86);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 50;
}
.header-inner {
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 24px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: var(--text);
}
.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--primary-grad);
  color: #fff;
  font-size: 19px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-primary);
  letter-spacing: -.5px;
}
.brand-text { display: flex; flex-direction: column; line-height: 1.2; }
.brand-text strong { font-size: 16px; font-weight: 800; letter-spacing: .3px; }
.brand-text small { font-size: 11px; color: var(--text-mute); margin-top: 2px; letter-spacing: .4px; }

.nav { display: flex; gap: 4px; }
.nav-item {
  padding: 8px 16px;
  text-decoration: none;
  color: var(--text-sub);
  font-size: 14px;
  font-weight: 500;
  border-radius: 999px;
  transition: all .18s ease;
}
.nav-item:hover { color: var(--primary); background: var(--primary-50); }
.nav-item.active {
  color: #fff;
  background: var(--primary-grad);
  box-shadow: 0 4px 12px rgba(43,110,243,.30);
  font-weight: 600;
}

.main { flex: 1; min-height: 0; max-width: 1400px; width: 100%; margin: 0 auto; padding: 16px 24px 20px; display: flex; flex-direction: column; overflow-y: auto; }

.footer {
  text-align: center;
  padding: 22px 16px 30px;
  color: var(--text-mute);
  font-size: 12px;
  letter-spacing: .4px;
}

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: #d0d8e2; border-radius: 8px; }
::-webkit-scrollbar-thumb:hover { background: #b8c2cf; }
::-webkit-scrollbar-track { background: transparent; }

@media (max-width: 720px) {
  .header-inner { height: auto; flex-direction: column; padding: 12px 16px 10px; gap: 8px; }
  .nav { width: 100%; justify-content: center; flex-wrap: wrap; }
  .main { padding: 20px 14px 44px; }
}
</style>
