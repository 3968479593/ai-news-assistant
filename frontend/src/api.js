// 后端 API 封装（fetch，无鉴权；开发环境经 Vite 代理，生产由后端同源托管）
async function handle(res) {
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${text.slice(0, 120)}`)
  }
  return res.json()
}

// 前端展示的活跃模块（仅列有稳定数据源的；体育/娱乐/健康/生活暂无源，隐藏等有源再放）
export const ACTIVE_CATEGORIES = ['科技', '商业财经', '国际', '综合']

export const api = {
  get(url) {
    return fetch(url).then(handle)
  },
  post(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle)
  },
  put(url, body) {
    return fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle)
  },
  delete(url) {
    return fetch(url, { method: 'DELETE' }).then(handle)
  },
}
