const API_BASE = '/api'

let currentKB = 'default'
export function setCurrentKB(name) { currentKB = name }
export function getCurrentKB() { return currentKB }

// 从 localStorage 读取 token
function getToken() {
  try {
    const saved = localStorage.getItem('raganything_auth')
    return saved ? JSON.parse(saved).token : ''
  } catch { return '' }
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
  const res = await fetch(`${API_BASE}${kbUrl(url)}`, {
    headers: authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) }),
    ...options,
    headers: authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) }),
  })
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
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // KB Management
  listKBs: () => fetchJson('/kb/list'),
  createKB: (name, label) => fetchJson(`/kb/create?kb_name=${name}&label=${encodeURIComponent(label)}`, { method: 'POST' }),
  switchKB: (name) => { currentKB = name; return fetchJson(`/kb/switch?name=${name}`, { method: 'PUT' }) },
  deleteKB: (name) => fetchJson(`/kb/${name}`, { method: 'DELETE' }),

  // Upload (FormData - no Content-Type so browser sets multipart boundary)
  uploadFile: (file, chunking_strategy = '') => {
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

  // Query
  query: (query, mode = 'hybrid', vlm = false) => request('/query', {
    method: 'POST', body: JSON.stringify({ query, mode, vlm_enhanced: vlm }),
  }),
  getQueryHistory: (limit = 20) => request(`/query/history?limit=${limit}`),
  clearQueryHistory: () => request('/query/history', { method: 'DELETE' }),

  // Settings
  getSettings: () => request('/settings'),
  updateSettings: (data) => request('/settings', { method: 'PUT', body: JSON.stringify(data) }),

  // Monitor
  getStatus: () => request('/monitor/status'),
  getLLMStats: () => request('/monitor/stats'),
  getLogs: (limit = 50) => request(`/monitor/logs?limit=${limit}`),
  health: () => request('/health'),

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
