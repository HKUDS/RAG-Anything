const API_BASE = '/api'

let currentKB = 'default'
export function setCurrentKB(name) { currentKB = name }
export function getCurrentKB() { return currentKB }

function kbUrl(path) {
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}kb=${currentKB}`
}

async function request(url, options = {}) {
  const res = await fetch(`${API_BASE}${kbUrl(url)}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // KB Management
  listKBs: () => fetch(`${API_BASE}/kb/list`).then(r => r.json()),
  createKB: (name, label) => fetch(`${API_BASE}/kb/create?kb_name=${name}&label=${encodeURIComponent(label)}`, { method: 'POST' }).then(r => r.json()),
  switchKB: (name) => { currentKB = name; return fetch(`${API_BASE}/kb/switch?name=${name}`, { method: 'PUT' }).then(r => r.json()) },
  deleteKB: (name) => fetch(`${API_BASE}/kb/${name}`, { method: 'DELETE' }).then(r => r.json()),

  // Upload (supports optional chunking_strategy)
  uploadFile: (file, chunking_strategy = '') => {
    const fd = new FormData(); fd.append('file', file)
    const strategyParam = chunking_strategy ? `&chunking_strategy=${chunking_strategy}` : ''
    return fetch(`${API_BASE}/upload?kb=${currentKB}${strategyParam}`, { method: 'POST', body: fd }).then(r => r.json())
  },
  uploadFiles: (files, chunking_strategy = '') => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    const strategyParam = chunking_strategy ? `&chunking_strategy=${chunking_strategy}` : ''
    return fetch(`${API_BASE}/upload/batch?kb=${currentKB}${strategyParam}`, { method: 'POST', body: fd }).then(r => r.json())
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
  listAgents: () => fetch(`${API_BASE}/agents`).then(r => r.json()),
  getAgentTemplates: () => fetch(`${API_BASE}/agents/templates`).then(r => r.json()),
  createAgent: (data) => fetch(`${API_BASE}/agents`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(r => r.json()),
  updateAgent: (id, data) => fetch(`${API_BASE}/agents/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(r => r.json()),
  deleteAgent: (id) => fetch(`${API_BASE}/agents/${id}`, { method: 'DELETE' }).then(r => r.json()),

  // Agent Conversations
  listConversations: (agentId) => fetch(`${API_BASE}/agents/${agentId}/conversations`).then(r => r.json()),
  createConversation: (agentId, title) => fetch(`${API_BASE}/agents/${agentId}/conversations?title=${encodeURIComponent(title)}`, { method: 'POST' }).then(r => r.json()),
  updateConversation: (agentId, threadId, title) => fetch(`${API_BASE}/agents/${agentId}/conversations/${threadId}?title=${encodeURIComponent(title)}`, { method: 'PUT' }).then(r => r.json()),
  deleteConversation: (agentId, threadId) => fetch(`${API_BASE}/agents/${agentId}/conversations/${threadId}`, { method: 'DELETE' }).then(r => r.json()),
}
