const API_BASE = '/api'
const UPLOAD_TIMEOUT_MS = 600_000 // 600s — aligned with nginx proxy_read_timeout
const KB_STATS_TIMEOUT_MS = 8_000
const KB_LIST_TIMEOUT_MS = 8_000
const KB_LIST_CACHE_TTL_MS = 5_000

let currentKB = ''
let kbListInFlight = null
let kbListCache = null
let kbListCacheAt = 0
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

function _uploadErrorMsg(status, detail) {
  if (status === 413) return '文件过大：超过服务器上传限制，请压缩后重试'
  if (status === 409) return '文件重复：该文件已存在或正在处理中'
  if (status >= 500) return '服务器错误：上传失败，请稍后重试'
  return detail || `上传失败 (HTTP ${status})`
}

function kbUrl(path) {
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}kb=${currentKB}`
}

function clearKBListCache() {
  kbListInFlight = null
  kbListCache = null
  kbListCacheAt = 0
}

async function readResponseBody(res, emptyValue = {}) {
  if (res.status === 204) return emptyValue
  const text = await res.text()
  if (!text.trim()) return emptyValue
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function buildHttpError(err, status) {
  const error = new Error(typeof err === 'string'
    ? (err || `HTTP ${status}`)
    : (
    typeof err?.detail === 'string' ? err.detail
    : Array.isArray(err?.detail) ? err.detail.map(e => e.msg || JSON.stringify(e)).join('; ')
    : `HTTP ${status}`
    ))
  error.status = status
  error.detail = typeof err === 'object' ? err?.detail : err
  return error
}

async function readUploadJsonResponse(res) {
  if (!res.ok) {
    const err = await readResponseBody(res, { detail: res.statusText })
    const detail = typeof err === 'string' ? err : err?.detail
    throw new Error(_uploadErrorMsg(res.status, detail))
  }

  const data = await readResponseBody(res, {})
  if (typeof data === 'string') {
    throw new Error('服务器返回了无效的 JSON 响应')
  }
  return data
}

async function listAllKnowledgeTags({ kb, query = '', signal } = {}) {
  const pageSize = 200
  const tags = []
  const seen = new Set()
  let offset = 0
  while (true) {
    const result = await fetchJson(
      `/knowledge/tags?kb=${encodeURIComponent(kb)}&q=${encodeURIComponent(query)}&limit=${pageSize}&offset=${offset}`,
      { signal },
    )
    const page = Array.isArray(result.tags) ? result.tags : []
    page.forEach(tag => {
      const key = String(tag.id)
      if (!seen.has(key)) {
        seen.add(key)
        tags.push(tag)
      }
    })
    if (page.length < pageSize) break
    offset += page.length
  }
  return { tags }
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
    const err = await readResponseBody(res, { detail: res.statusText })
    throw buildHttpError(err, res.status)
  }
  const data = await readResponseBody(res, {})
  if (typeof data === 'string') {
    throw new Error('服务器返回了无效的 JSON 响应')
  }
  return data
}

async function fetchJson(url, options = {}) {
  const { timeoutMs = 0, signal, ...restOptions } = options
  const controller = timeoutMs > 0 ? new AbortController() : null
  const activeSignal = controller ? controller.signal : signal
  const timeoutId = controller
    ? setTimeout(() => controller.abort(), timeoutMs)
    : null
  const abortForwarder = controller && signal
    ? () => controller.abort()
    : null

  if (signal && abortForwarder) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', abortForwarder, { once: true })
  }

  let res
  try {
    res = await fetch(`${API_BASE}${url}`, {
      headers: authHeaders({ 'Content-Type': 'application/json', ...(restOptions.headers || {}) }),
      ...restOptions,
      signal: activeSignal,
      headers: authHeaders({ 'Content-Type': 'application/json', ...(restOptions.headers || {}) }),
    })
  } catch (err) {
    if (timeoutId) clearTimeout(timeoutId)
    if (signal && abortForwarder) signal.removeEventListener('abort', abortForwarder)
    if (err.name === 'AbortError') throw new Error('请求超时，请稍后重试')
    if (err.message === 'Failed to fetch') throw new Error('网络错误：请检查前后端服务是否正常')
    throw err
  }

  if (timeoutId) clearTimeout(timeoutId)
  if (signal && abortForwarder) signal.removeEventListener('abort', abortForwarder)
  if (res.status === 401) { handleAuthError(); throw new Error('登录已过期，请重新登录') }
  if (!res.ok) {
    const err = await readResponseBody(res, { detail: res.statusText })
    throw buildHttpError(err, res.status)
  }
  const data = await readResponseBody(res, {})
  if (typeof data === 'string') {
    throw new Error('服务器返回了无效的 JSON 响应')
  }
  return data
}

export const api = {
  // 通用 HTTP 方法
  get: (url, config = {}) => {
    const params = config.params
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return fetchJson(`${url}${qs}`)
  },
  post: (url, data) => fetchJson(url, { method: 'POST', body: JSON.stringify(data) }),
  put: (url, data) => fetchJson(url, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (url) => fetchJson(url, { method: 'DELETE' }),

  // 知识库管理
  listKBs: ({ force = false } = {}) => {
    if (!force && kbListCache && (Date.now() - kbListCacheAt) < KB_LIST_CACHE_TTL_MS) {
      return Promise.resolve(kbListCache)
    }
    if (!kbListInFlight) {
      kbListInFlight = fetchJson('/kb/list', { timeoutMs: KB_LIST_TIMEOUT_MS })
        .then(response => {
          kbListCache = response
          kbListCacheAt = Date.now()
          return response
        })
        .finally(() => {
          kbListInFlight = null
        })
    }
    return kbListInFlight
  },
  createKB: (name, label) => fetchJson(`/kb/create?kb_name=${name}&label=${encodeURIComponent(label)}`, { method: 'POST' })
    .then(response => {
      clearKBListCache()
      return response
    }),
  switchKB: (name) => {
    currentKB = name
    return fetchJson(`/kb/switch?name=${name}`, { method: 'PUT' }).then(response => {
      clearKBListCache()
      return response
    })
  },
  deleteKB: (name) => fetchJson(`/kb/${name}`, { method: 'DELETE' })
    .then(response => {
      clearKBListCache()
      return response
    }),

  // 上传（FormData 不手动设置 Content-Type，由浏览器设置 multipart 边界）
  uploadFile: (file, chunking_strategy = '', multimodal = {}) => {
    if (!currentKB) { console.warn('[api] 跳过 upload：currentKB 未初始化'); return Promise.reject(new Error('知识库未就绪')) }
    const fd = new FormData(); fd.append('file', file)
    const params = new URLSearchParams()
    if (chunking_strategy) params.set('chunking_strategy', chunking_strategy)
    if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
    if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
    if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
    if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
    const qs = params.toString()
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS)
    return fetch(`${API_BASE}/upload?kb=${currentKB}${qs ? '&' + qs : ''}`, {
      method: 'POST', body: fd, headers: authHeaders(), signal: controller.signal
    }).then(r => {
      clearTimeout(timeoutId)
      return readUploadJsonResponse(r)
    }).catch(err => {
      clearTimeout(timeoutId)
      if (err.name === 'AbortError') throw new Error('上传超时：文件过大或网络较慢，请重试')
      if (err.message === 'Failed to fetch') throw new Error('网络错误：上传中断，请检查网络连接后重试')
      throw err
    })
  },
  uploadFiles: (files, chunking_strategy = '', multimodal = {}) => {
    if (!currentKB) { console.warn('[api] 跳过 uploadFiles：currentKB 未初始化'); return Promise.reject(new Error('知识库未就绪')) }
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    const params = new URLSearchParams()
    if (chunking_strategy) params.set('chunking_strategy', chunking_strategy)
    if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
    if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
    if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
    if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
    const qs = params.toString()
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS)
    return fetch(`${API_BASE}/upload/batch?kb=${currentKB}${qs ? '&' + qs : ''}`, {
      method: 'POST', body: fd, headers: authHeaders(), signal: controller.signal
    }).then(r => {
      clearTimeout(timeoutId)
      return readUploadJsonResponse(r)
    }).catch(err => {
      clearTimeout(timeoutId)
      if (err.name === 'AbortError') throw new Error('上传超时：文件过大或网络较慢，请重试')
      if (err.message === 'Failed to fetch') throw new Error('网络错误：上传中断，请检查网络连接后重试')
      throw err
    })
  },
  uploadFolder: (path, chunking_strategy = '', multimodal = {}) => {
    const params = new URLSearchParams()
    params.set('folder_path', path)
    if (chunking_strategy) params.set('chunking_strategy', chunking_strategy)
    if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
    if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
    if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
    if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
    const qs = params.toString()
    return request(`/upload/folder${qs ? '?' + qs : ''}`, { method: 'POST' })
  },
  uploadUrl: (url, { strategy = '', multimodal = {} } = {}) => {
    const params = new URLSearchParams()
    params.set('url', url)
    if (strategy) params.set('chunking_strategy', strategy)
    if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
    if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
    if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
    if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
    return request(`/upload/url?${params.toString()}`, { method: 'POST' })
  },
  uploadContent: (content, title, chunking_strategy = '', multimodal = {}) => {
    const params = new URLSearchParams()
    if (chunking_strategy) params.set('chunking_strategy', chunking_strategy)
    if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
    if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
    if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
    if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
    const qs = params.toString()
    return request(`/upload/content${qs ? '?' + qs : ''}`, { method: 'POST', body: JSON.stringify({ content, title }) })
  },

  // 知识相关接口
  getDocuments: () => request('/knowledge/documents'),
  getStats: () => request('/knowledge/stats'),
  getStatsForKB: (kbName) => fetchJson(`/knowledge/stats?kb=${encodeURIComponent(kbName)}`),
  getStatsBatchForKBs: (kbNames) => fetchJson('/knowledge/stats/batch', {
    method: 'POST',
    body: JSON.stringify({ kb_names: kbNames }),
    timeoutMs: KB_STATS_TIMEOUT_MS,
  }),
  getEntities: (limit = 50) => request(`/knowledge/entities?limit=${limit}`),
  getGraph: () => request('/knowledge/graph'),
  getGraphNode: (name) => request(`/knowledge/graph/nodes/${encodeURIComponent(name)}`),
  createGraphNode: (data) => request('/knowledge/graph/nodes', { method: 'POST', body: JSON.stringify(data) }),
  renameGraphNode: (name, newName) => request(`/knowledge/graph/nodes/${encodeURIComponent(name)}`, { method: 'PUT', body: JSON.stringify({ new_name: newName }) }),
  deleteGraphNode: (name) => request(`/knowledge/graph/nodes/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  createGraphEdge: (data) => request('/knowledge/graph/edges', { method: 'POST', body: JSON.stringify(data) }),
  deleteGraphEdge: (id) => request(`/knowledge/graph/edges/${id}`, { method: 'DELETE' }),
  getDocumentChunks: (docId, { kb = currentKB, signal } = {}) => fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks?kb=${encodeURIComponent(kb)}`,
    { signal }
  ),
  regenerateDocumentTags: (docId, { kb = currentKB } = {}) => request(
    `/knowledge/documents/${encodeURIComponent(docId)}/tags/regenerate?kb=${encodeURIComponent(kb)}`,
    { method: 'POST' },
  ),
  getDocumentChunk: (docId, chunkId, { kb = currentKB, signal } = {}) => fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}?kb=${encodeURIComponent(kb)}`,
    { signal }
  ),
  listKnowledgeTags: ({ kb = currentKB, query = '', limit = 100, offset = 0, signal } = {}) => fetchJson(
    `/knowledge/tags?kb=${encodeURIComponent(kb)}&q=${encodeURIComponent(query)}&limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`,
    { signal }
  ),
  listAllKnowledgeTags: ({ kb = currentKB, query = '', signal } = {}) => (
    listAllKnowledgeTags({ kb, query, signal })
  ),
  getKnowledgeTagLinks: (tagId, { kb = currentKB, signal } = {}) => fetchJson(
    `/knowledge/tags/${encodeURIComponent(tagId)}/links?kb=${encodeURIComponent(kb)}`,
    { signal }
  ),
  updateDocumentChunkTags: (docId, chunkId, tagNames, { kb = currentKB } = {}) => fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}/tags?kb=${encodeURIComponent(kb)}`,
    { method: 'PUT', body: JSON.stringify({ tag_names: tagNames }) }
  ),
  updateDocumentChunk: (docId, chunkId, content, { kb = currentKB } = {}) => fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}?kb=${encodeURIComponent(kb)}`,
    { method: 'PATCH', body: JSON.stringify({ content }) }
  ),
  deleteDocumentChunk: (docId, chunkId, { kb = currentKB } = {}) => fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}?kb=${encodeURIComponent(kb)}`,
    { method: 'DELETE' }
  ),
  deleteDocument: (id) => request(`/knowledge/documents/${id}`, { method: 'DELETE' }),
  deleteDocuments: (ids) => request('/knowledge/documents/batch-delete', { method: 'POST', body: JSON.stringify({ doc_ids: ids }) }),
  retryDocument: (id) => request(`/knowledge/documents/${id}/retry`, { method: 'POST' }),
  getUploadTasks: () => request('/upload/tasks'),
  deleteUploadTask: (taskId) => request(`/upload/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' }),
  retryUploadTaskNow: (taskId) => request(`/upload/tasks/${encodeURIComponent(taskId)}/retry-now`, { method: 'POST' }),
  cancelUploadRetry: (taskId) => request(`/upload/tasks/${encodeURIComponent(taskId)}/cancel-retry`, { method: 'POST' }),
  reprocessMultimodal: (kbName) => fetchJson(`/kb/${encodeURIComponent(kbName)}/reprocess-multimodal`, { method: 'POST' }),
  downloadDocumentUrl: (id, kb = currentKB) => {
    const token = getToken()
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : ''
    return `${API_BASE}/knowledge/documents/${encodeURIComponent(id)}/download?kb=${encodeURIComponent(kb)}${tokenParam}`
  },

  // 图像相似度搜索（视觉嵌入：doubao-embedding-vision）
  imageSearch: (file, topK = 10) => {
    if (!currentKB) { console.warn('[api] 跳过 imageSearch：currentKB 未初始化'); return Promise.reject(new Error('知识库未就绪')) }
    const fd = new FormData(); fd.append('image', file)
    return fetch(`${API_BASE}/knowledge/image-search?kb=${currentKB}&top_k=${topK}`, {
      method: 'POST', body: fd, headers: authHeaders()
    }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail || r.statusText) })
      return r.json()
    })
  },

  // 设置接口（仅管理员；使用 fetchJson 避免附加 ?kb= 参数）
  getSettings: () => fetchJson('/settings'),
  updateSettings: (data) => fetchJson('/settings', { method: 'PUT', body: JSON.stringify(data) }),
  resetSettings: () => fetchJson('/settings/reset', { method: 'POST' }),

  // 监控
  getStatus: () => fetchJson('/monitor/status'),
  getLLMStats: () => fetchJson('/monitor/stats'),
  getLogs: (limit = 50) => fetchJson(`/monitor/logs?limit=${limit}`),
  getAuditHealth: () => fetchJson('/admin/health/audit'),
  getCacheStats: () => fetchJson('/cache/stats'),
  reloadKB: (kbName) => fetchJson(`/reload-kb/${encodeURIComponent(kbName)}`, { method: 'POST' }),
  evictKB: (kbName) => fetchJson(`/cache/evict/${encodeURIComponent(kbName)}`, { method: 'POST' }),
  pinKB: (kbName) => fetchJson(`/cache/pin/${encodeURIComponent(kbName)}`, { method: 'POST' }),
  unpinKB: (kbName) => fetchJson(`/cache/unpin/${encodeURIComponent(kbName)}`, { method: 'POST' }),
  health: () => fetchJson('/health'),

  // 智能体
  listAgents: () => fetchJson('/agents'),
  getAgentTemplates: () => fetchJson('/agents/templates'),
  createAgent: (data) => fetchJson('/agents', { method: 'POST', body: JSON.stringify(data) }),
  updateAgent: (id, data) => fetchJson(`/agents/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteAgent: (id) => fetchJson(`/agents/${id}`, { method: 'DELETE' }),

  // 智能体会话
  listConversations: (agentId) => fetchJson(`/agents/${agentId}/conversations`),
  createConversation: (agentId, title) => fetchJson(`/agents/${agentId}/conversations?title=${encodeURIComponent(title)}`, { method: 'POST' }),
  updateConversation: (agentId, threadId, title) => fetchJson(`/agents/${agentId}/conversations/${threadId}?title=${encodeURIComponent(title)}`, { method: 'PUT' }),
  getConversation: (agentId, threadId) => fetchJson(`/agents/${agentId}/conversations/${threadId}`),
  deleteConversation: (agentId, threadId) => fetchJson(`/agents/${agentId}/conversations/${threadId}`, { method: 'DELETE' }),

  // 消息编辑
  updateMessage: (agentId, threadId, messageId, content) =>
    fetchJson(`/agents/${agentId}/conversations/${threadId}/messages/${messageId}`,
      { method: 'PUT', body: JSON.stringify({ content }) }),

}
