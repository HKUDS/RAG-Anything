const API_BASE = '/api'

let currentKB = ''
export function setCurrentKB(name) { currentKB = name }
export function getCurrentKB() { return currentKB }

// 从 localStorage 读取 token
export function getToken() {
  try {
    const saved = localStorage.getItem('raganything_auth')
    return saved ? JSON.parse(saved).token : ''
  } catch { return '' }
}

function handleAuthError() {
  localStorage.removeItem('raganything_auth')
  window.dispatchEvent(new CustomEvent('raganything:auth-expired'))
}

function authHeaders(extra = {}) {
  const token = getToken()
  const h = { ...extra }
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

function kbUrl(path) {
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}kb=${currentKB}`
}

async function request(url, options = {}) {
  if (!currentKB) {
    console.warn(`[api] 跳过请求 ${url}：currentKB 未初始化`)
    return {}
  }
  const res = await fetch(`${API_BASE}${kbUrl(url)}`, {
    headers: authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) }),
    ...options,
    headers: authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) }),
  })
  if (res.status === 401) { handleAuthError(); throw new Error('登录已过期，请重新登录') }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

async function fetchJson(url, options = {}) {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) }),
    ...options,
    headers: authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) }),
  })
  if (res.status === 401) { handleAuthError(); throw new Error('登录已过期，请重新登录') }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // Generic HTTP methods
  get: (url, config = {}) => {
    const params = config.params
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return fetchJson(`${url}${qs}`)
  },
  post: (url, data) => fetchJson(url, { method: 'POST', body: JSON.stringify(data) }),
  put: (url, data) => fetchJson(url, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (url) => fetchJson(url, { method: 'DELETE' }),

  // KB Management
  listKBs: () => fetchJson('/kb/list'),
  createKB: (name, label) => fetchJson(`/kb/create?kb_name=${name}&label=${encodeURIComponent(label)}`, { method: 'POST' }),
  switchKB: (name) => { currentKB = name; return fetchJson(`/kb/switch?name=${name}`, { method: 'PUT' }) },
  deleteKB: (name) => fetchJson(`/kb/${name}`, { method: 'DELETE' }),

  // Upload (FormData - no Content-Type so browser sets multipart boundary)
  uploadFile: (file, chunking_strategy = '') => {
    if (!currentKB) { console.warn('[api] 跳过 upload：currentKB 未初始化'); return Promise.reject(new Error('知识库未就绪')) }
    const fd = new FormData(); fd.append('file', file)
    const strategyParam = chunking_strategy ? `&chunking_strategy=${chunking_strategy}` : ''
    return fetch(`${API_BASE}/upload?kb=${currentKB}${strategyParam}`, {
      method: 'POST', body: fd, headers: authHeaders()
    }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail || r.statusText) })
      return r.json()
    })
  },
  uploadFiles: (files, chunking_strategy = '') => {
    if (!currentKB) { console.warn('[api] 跳过 uploadFiles：currentKB 未初始化'); return Promise.reject(new Error('知识库未就绪')) }
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    const strategyParam = chunking_strategy ? `&chunking_strategy=${chunking_strategy}` : ''
    return fetch(`${API_BASE}/upload/batch?kb=${currentKB}${strategyParam}`, {
      method: 'POST', body: fd, headers: authHeaders()
    }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail || r.statusText) })
      return r.json()
    })
  },
  uploadFolder: (path, chunking_strategy = '') => {
    const strategyParam = chunking_strategy ? `&chunking_strategy=${chunking_strategy}` : ''
    return request(`/upload/folder${strategyParam ? '?' + strategyParam.slice(1) : ''}`, { method: 'POST', body: JSON.stringify({ folder_path: path }) })
  },
  uploadContent: (content, title, chunking_strategy = '') => {
    const strategyParam = chunking_strategy ? `&chunking_strategy=${chunking_strategy}` : ''
    return request(`/upload/content${strategyParam ? '?' + strategyParam.slice(1) : ''}`, { method: 'POST', body: JSON.stringify({ content, title }) })
  },

  // Knowledge
  getDocuments: () => request('/knowledge/documents'),
  getStats: () => request('/knowledge/stats'),
  getEntities: (limit = 50) => request(`/knowledge/entities?limit=${limit}`),
  getGraph: () => request('/knowledge/graph'),
  deleteDocument: (id) => request(`/knowledge/documents/${id}`, { method: 'DELETE' }),
  deleteDocuments: (ids) => request('/knowledge/documents/batch-delete', { method: 'POST', body: JSON.stringify({ doc_ids: ids }) }),
  retryDocument: (id) => request(`/knowledge/documents/${id}/retry`, { method: 'POST' }),

  // Settings (admin only — uses fetchJson to avoid ?kb= param)
  getSettings: () => fetchJson('/settings'),
  updateSettings: (data) => fetchJson('/settings', { method: 'PUT', body: JSON.stringify(data) }),

  // Monitor
  getStatus: () => fetchJson('/monitor/status'),
  getLLMStats: () => fetchJson('/monitor/stats'),
  getLogs: (limit = 50) => fetchJson(`/monitor/logs?limit=${limit}`),
  health: () => fetchJson('/health'),

  // Agents
  listAgents: () => fetchJson('/agents'),
  getAgentTemplates: () => fetchJson('/agents/templates'),
  createAgent: (data) => fetchJson('/agents', { method: 'POST', body: JSON.stringify(data) }),
  updateAgent: (id, data) => fetchJson(`/agents/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteAgent: (id) => fetchJson(`/agents/${id}`, { method: 'DELETE' }),

  // Agent Conversations
  listConversations: (agentId) => fetchJson(`/agents/${agentId}/conversations`),
  createConversation: (agentId, title) => fetchJson(`/agents/${agentId}/conversations?title=${encodeURIComponent(title)}`, { method: 'POST' }),
  updateConversation: (agentId, threadId, title) => fetchJson(`/agents/${agentId}/conversations/${threadId}?title=${encodeURIComponent(title)}`, { method: 'PUT' }),
  deleteConversation: (agentId, threadId) => fetchJson(`/agents/${agentId}/conversations/${threadId}`, { method: 'DELETE' }),

}
