const API_BASE = '/api'
import { knowledgeDetailCache } from './knowledgeDetailCache.js'

const UPLOAD_TIMEOUT_MS = 600_000 // 600s — aligned with nginx proxy_read_timeout
const KB_STATS_TIMEOUT_MS = 8_000
const KB_LIST_TIMEOUT_MS = 8_000
const KB_LIST_CACHE_TTL_MS = 5_000
const KB_DETAIL_PREFETCH_TIMEOUT_MS = 6_000

let currentKB = ''
let kbListInFlight = null
let kbListCache = null
let kbListCacheAt = 0
let kbListEpoch = 0
export function setCurrentKB(name) { currentKB = name }
export function getCurrentKB() { return currentKB }

export function getCachedKnowledgeDetail(kbName) {
  if (!kbName) return null
  const snapshot = knowledgeDetailCache.read(kbName)
  if (!snapshot) return null
  return {
    ...snapshot.value,
    cacheFresh: snapshot.fresh,
    cacheAgeMs: snapshot.ageMs,
  }
}

export function invalidateKnowledgeDetail(kbName) {
  if (kbName) knowledgeDetailCache.invalidate(kbName)
}

export function clearKnowledgeDetailCache() {
  knowledgeDetailCache.invalidateAll()
}

export function advanceKnowledgeDetailAuthGeneration() {
  const current = Number(knowledgeDetailCache.getAuthGeneration()) || 0
  knowledgeDetailCache.setAuthGeneration(current + 1)
  currentKB = ''
  clearKBListCache()
}

// 从 localStorage 读取 token
export function getToken() {
  try {
    const saved = localStorage.getItem('raganything_auth')
    return saved ? JSON.parse(saved).token : ''
  } catch { return '' }
}

function handleAuthError() {
  advanceKnowledgeDetailAuthGeneration()
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
  kbListEpoch += 1
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
  if (res.status === 401) {
    handleAuthError()
    const error = new Error('登录已过期，请重新登录')
    error.status = 401
    throw error
  }
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
  let timedOut = false
  const timeoutId = controller
    ? setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
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
    if (err.name === 'AbortError') {
      if (signal?.aborted && !timedOut) {
        const cancelled = new Error('请求已取消')
        cancelled.name = 'AbortError'
        throw cancelled
      }
      const timeoutError = new Error('请求超时，请稍后重试')
      timeoutError.code = 'REQUEST_TIMEOUT'
      throw timeoutError
    }
    if (err.message === 'Failed to fetch') throw new Error('网络错误：请检查前后端服务是否正常')
    throw err
  }

  if (timeoutId) clearTimeout(timeoutId)
  if (signal && abortForwarder) signal.removeEventListener('abort', abortForwarder)
  if (res.status === 401) {
    handleAuthError()
    const error = new Error('登录已过期，请重新登录')
    error.status = 401
    throw error
  }
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

function streamErrorMessage(payload, fallback) {
  if (typeof payload === 'string') return payload || fallback
  if (typeof payload?.detail === 'string') return payload.detail
  if (payload?.detail && typeof payload.detail === 'object') {
    return payload.detail.message || payload.detail.error || payload.detail.code || fallback
  }
  if (typeof payload?.message === 'string') return payload.message
  return fallback
}

export async function streamSSE(url, {
  method = 'POST', body, headers = {}, signal, onEvent, onParseError,
} = {}) {
  let response
  try {
    response = await fetch(url, {
      method,
      body,
      signal,
      headers: authHeaders({ 'Content-Type': 'application/json', ...headers }),
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    if (error?.message === 'Failed to fetch') throw new Error('网络错误：请检查前后端服务是否正常')
    throw error
  }

  if (response.status === 401) {
    handleAuthError()
  }
  if (!response.ok) {
    const payload = await readResponseBody(response, response.statusText || `HTTP ${response.status}`)
    const error = new Error(streamErrorMessage(payload, response.statusText || `HTTP ${response.status}`))
    error.status = response.status
    throw error
  }
  if (!response.body) throw new Error('问答连接意外中断，请重试。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let terminal = false
  const consumeLine = line => {
    const normalized = line.replace(/\r$/, '')
    if (!normalized.startsWith('data:')) return
    const raw = normalized.slice(5).trimStart()
    if (!raw) return
    let event
    try {
      event = JSON.parse(raw)
    } catch (error) {
      onParseError?.(error, raw)
      return
    }
    onEvent?.(event)
    if (event?.type === 'done' || event?.type === 'error') terminal = true
  }

  try {
    while (!terminal) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        consumeLine(line)
        if (terminal) break
      }
    }
    if (!terminal) {
      buffer += decoder.decode()
      if (buffer.trim()) consumeLine(buffer)
    }
    if (!terminal) throw new Error('问答连接意外中断，请重试。')
  } finally {
    if (terminal) await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

function detailResource(result, selectData) {
  if (result.status === 'fulfilled') {
    return { status: 'ready', data: selectData(result.value), error: '' }
  }
  return {
    status: 'error',
    data: null,
    error: result.reason?.message || '加载失败，请重试',
    httpStatus: result.reason?.status || 0,
    failClosed: result.reason?.status === 401 || result.reason?.status === 403,
  }
}

function abortError() {
  const error = new Error('请求已取消')
  error.name = 'AbortError'
  return error
}

function waitForSharedRequest(request, signal) {
  if (!signal) return request
  if (signal.aborted) return Promise.reject(abortError())

  return new Promise((resolve, reject) => {
    const handleAbort = () => reject(abortError())
    signal.addEventListener('abort', handleAbort, { once: true })
    request.then(resolve, reject).finally(() => {
      signal.removeEventListener('abort', handleAbort)
    })
  })
}

async function loadKnowledgeDetailSnapshot(kbName, { timeoutMs = KB_DETAIL_PREFETCH_TIMEOUT_MS } = {}) {
  const encodedKB = encodeURIComponent(kbName)
  const [documentsResult, statsResult] = await Promise.allSettled([
    fetchJson(`/knowledge/documents?kb=${encodedKB}`, { timeoutMs }),
    fetchJson(`/knowledge/stats?kb=${encodedKB}`, { timeoutMs }),
  ])
  const accessDenied = [documentsResult, statsResult].some(result => (
    result.status === 'rejected'
    && (result.reason?.status === 401 || result.reason?.status === 403)
  ))
  if (accessDenied) invalidateKnowledgeDetail(kbName)
  return {
    kbName,
    documents: detailResource(documentsResult, value => value.documents || []),
    stats: detailResource(statsResult, value => value || {}),
  }
}

export function prefetchKnowledgeDetail(
  kbName,
  { force = false, signal, timeoutMs = KB_DETAIL_PREFETCH_TIMEOUT_MS } = {},
) {
  const cached = knowledgeDetailCache.read(kbName)
  const cachedHasError = cached?.value?.documents?.status === 'error'
    || cached?.value?.stats?.status === 'error'
  const sharedRequest = knowledgeDetailCache.load(
    kbName,
    () => loadKnowledgeDetailSnapshot(kbName, { timeoutMs }),
    { force: force || cachedHasError },
  )
  return waitForSharedRequest(sharedRequest, signal)
}

function invalidateAfter(promise, kbName) {
  return promise.then(response => {
    invalidateKnowledgeDetail(kbName)
    return response
  })
}

export const api = {
  // 通用 HTTP 方法
  get: (url, config = {}) => {
    const { params, ...options } = config
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return fetchJson(`${url}${qs}`, options)
  },
  post: (url, data) => fetchJson(url, { method: 'POST', body: JSON.stringify(data) }),
  put: (url, data) => fetchJson(url, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (url) => fetchJson(url, { method: 'DELETE' }),
  getMe: () => fetchJson('/auth/me'),

  // 知识库管理
  listKBs: ({ force = false } = {}) => {
    if (!force && kbListCache && (Date.now() - kbListCacheAt) < KB_LIST_CACHE_TTL_MS) {
      return Promise.resolve(kbListCache)
    }
    if (!kbListInFlight) {
      const requestEpoch = kbListEpoch
      let request
      request = fetchJson('/kb/list', { timeoutMs: KB_LIST_TIMEOUT_MS })
        .then(response => {
          if (requestEpoch === kbListEpoch && kbListInFlight === request) {
            kbListCache = response
            kbListCacheAt = Date.now()
          }
          return response
        })
        .finally(() => {
          if (kbListInFlight === request) kbListInFlight = null
        })
      kbListInFlight = request
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
      invalidateKnowledgeDetail(name)
      return response
    }),

  // 上传（FormData 不手动设置 Content-Type，由浏览器设置 multipart 边界）
  uploadFile: (file, chunking_strategy = '', multimodal = {}) => {
    if (!currentKB) { console.warn('[api] 跳过 upload：currentKB 未初始化'); return Promise.reject(new Error('知识库未就绪')) }
    const requestKB = currentKB
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
    return fetch(`${API_BASE}/upload?kb=${requestKB}${qs ? '&' + qs : ''}`, {
      method: 'POST', body: fd, headers: authHeaders(), signal: controller.signal
    }).then(r => {
      clearTimeout(timeoutId)
      return readUploadJsonResponse(r)
    }).then(response => {
      invalidateKnowledgeDetail(requestKB)
      return response
    }).catch(err => {
      clearTimeout(timeoutId)
      if (err.name === 'AbortError') throw new Error('上传超时：文件过大或网络较慢，请重试')
      if (err.message === 'Failed to fetch') throw new Error('网络错误：上传中断，请检查网络连接后重试')
      throw err
    })
  },
  uploadFiles: (files, chunking_strategy = '', multimodal = {}) => {
    if (!currentKB) { console.warn('[api] 跳过 uploadFiles：currentKB 未初始化'); return Promise.reject(new Error('知识库未就绪')) }
    const requestKB = currentKB
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
    return fetch(`${API_BASE}/upload/batch?kb=${requestKB}${qs ? '&' + qs : ''}`, {
      method: 'POST', body: fd, headers: authHeaders(), signal: controller.signal
    }).then(r => {
      clearTimeout(timeoutId)
      return readUploadJsonResponse(r)
    }).then(response => {
      invalidateKnowledgeDetail(requestKB)
      return response
    }).catch(err => {
      clearTimeout(timeoutId)
      if (err.name === 'AbortError') throw new Error('上传超时：文件过大或网络较慢，请重试')
      if (err.message === 'Failed to fetch') throw new Error('网络错误：上传中断，请检查网络连接后重试')
      throw err
    })
  },
  uploadFolder: (path, chunking_strategy = '', multimodal = {}) => {
    const requestKB = currentKB
    if (!requestKB) return Promise.reject(new Error('知识库未就绪'))
    const params = new URLSearchParams()
    params.set('folder_path', path)
    if (chunking_strategy) params.set('chunking_strategy', chunking_strategy)
    if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
    if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
    if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
    if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
    params.set('kb', requestKB)
    return invalidateAfter(fetchJson(`/upload/folder?${params.toString()}`, { method: 'POST' }), requestKB)
  },
  uploadUrl: (url, { strategy = '', multimodal = {} } = {}) => {
    const requestKB = currentKB
    if (!requestKB) return Promise.reject(new Error('知识库未就绪'))
    const params = new URLSearchParams()
    params.set('url', url)
    if (strategy) params.set('chunking_strategy', strategy)
    if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
    if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
    if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
    if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
    params.set('kb', requestKB)
    return invalidateAfter(fetchJson(`/upload/url?${params.toString()}`, { method: 'POST' }), requestKB)
  },
  uploadContent: (content, title, chunking_strategy = '', multimodal = {}) => {
    const requestKB = currentKB
    if (!requestKB) return Promise.reject(new Error('知识库未就绪'))
    const params = new URLSearchParams()
    if (chunking_strategy) params.set('chunking_strategy', chunking_strategy)
    if (multimodal.enable_image !== undefined) params.set('enable_image', multimodal.enable_image)
    if (multimodal.enable_table !== undefined) params.set('enable_table', multimodal.enable_table)
    if (multimodal.enable_equation !== undefined) params.set('enable_equation', multimodal.enable_equation)
    if (multimodal.enable_video !== undefined) params.set('enable_video', multimodal.enable_video)
    params.set('kb', requestKB)
    return invalidateAfter(fetchJson(`/upload/content?${params.toString()}`, {
      method: 'POST', body: JSON.stringify({ content, title }),
    }), requestKB)
  },

  // 知识相关接口
  prefetchKnowledgeDetail: (kbName, options) => prefetchKnowledgeDetail(kbName, options),
  getCachedKnowledgeDetail: (kbName) => getCachedKnowledgeDetail(kbName),
  invalidateKnowledgeDetail: (kbName) => invalidateKnowledgeDetail(kbName),
  clearKnowledgeDetailCache: () => clearKnowledgeDetailCache(),
  getDocuments: () => request('/knowledge/documents'),
  getDocumentsForKB: (kbName, { signal, timeoutMs = 0 } = {}) => fetchJson(
    `/knowledge/documents?kb=${encodeURIComponent(kbName)}`,
    { signal, timeoutMs },
  ),
  getStats: () => request('/knowledge/stats'),
  getStatsForKB: (kbName, { signal, timeoutMs = 0 } = {}) => fetchJson(
    `/knowledge/stats?kb=${encodeURIComponent(kbName)}`,
    { signal, timeoutMs },
  ),
  getStatsBatchForKBs: (kbNames) => fetchJson('/knowledge/stats/batch', {
    method: 'POST',
    body: JSON.stringify({ kb_names: kbNames }),
    timeoutMs: KB_STATS_TIMEOUT_MS,
  }),
  getEntities: (limit = 50) => request(`/knowledge/entities?limit=${limit}`),
  getEntitiesForKB: (kbName, limit = 50, { signal } = {}) => fetchJson(
    `/knowledge/entities?limit=${encodeURIComponent(limit)}&kb=${encodeURIComponent(kbName)}`,
    { signal },
  ),
  getGraph: () => request('/knowledge/graph'),
  getGraphForKB: (kbName, { signal } = {}) => fetchJson(
    `/knowledge/graph?kb=${encodeURIComponent(kbName)}`,
    { signal },
  ),
  getGraphNode: (name) => request(`/knowledge/graph/nodes/${encodeURIComponent(name)}`),
  getGraphNodeForKB: (kbName, name, { signal } = {}) => fetchJson(
    `/knowledge/graph/nodes/${encodeURIComponent(name)}?kb=${encodeURIComponent(kbName)}`,
    { signal },
  ),
  createGraphNode: (data, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/graph/nodes?kb=${encodeURIComponent(kb)}`,
    { method: 'POST', body: JSON.stringify(data) },
  ), kb),
  renameGraphNode: (name, newName, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/graph/nodes/${encodeURIComponent(name)}?kb=${encodeURIComponent(kb)}`,
    { method: 'PUT', body: JSON.stringify({ new_name: newName }) },
  ), kb),
  deleteGraphNode: (name, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/graph/nodes/${encodeURIComponent(name)}?kb=${encodeURIComponent(kb)}`,
    { method: 'DELETE' },
  ), kb),
  createGraphEdge: (data, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/graph/edges?kb=${encodeURIComponent(kb)}`,
    { method: 'POST', body: JSON.stringify(data) },
  ), kb),
  deleteGraphEdge: (id, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/graph/edges/${id}?kb=${encodeURIComponent(kb)}`,
    { method: 'DELETE' },
  ), kb),
  getDocumentChunks: (docId, { kb = currentKB, signal } = {}) => fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks?kb=${encodeURIComponent(kb)}`,
    { signal }
  ),
  regenerateDocumentTags: (docId, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/tags/regenerate?kb=${encodeURIComponent(kb)}`,
    { method: 'POST' },
  ), kb),
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
  updateDocumentChunkTags: (docId, chunkId, tagNames, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}/tags?kb=${encodeURIComponent(kb)}`,
    { method: 'PUT', body: JSON.stringify({ tag_names: tagNames }) }
  ), kb),
  updateDocumentChunk: (docId, chunkId, content, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}?kb=${encodeURIComponent(kb)}`,
    { method: 'PATCH', body: JSON.stringify({ content }) }
  ), kb),
  deleteDocumentChunk: (docId, chunkId, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}?kb=${encodeURIComponent(kb)}`,
    { method: 'DELETE' }
  ), kb),
  deleteDocument: (id, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/documents/${encodeURIComponent(id)}?kb=${encodeURIComponent(kb)}`,
    { method: 'DELETE' },
  ), kb),
  deleteDocuments: (ids, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/documents/batch-delete?kb=${encodeURIComponent(kb)}`,
    { method: 'POST', body: JSON.stringify({ doc_ids: ids }) },
  ), kb),
  retryDocument: (id, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/knowledge/documents/${encodeURIComponent(id)}/retry?kb=${encodeURIComponent(kb)}`,
    { method: 'POST' },
  ), kb),
  getUploadTasks: () => request('/upload/tasks'),
  deleteUploadTask: (taskId) => request(`/upload/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' }),
  retryUploadTaskNow: (taskId, { kb = currentKB } = {}) => invalidateAfter(fetchJson(
    `/upload/tasks/${encodeURIComponent(taskId)}/retry-now?kb=${encodeURIComponent(kb)}`,
    { method: 'POST' },
  ), kb),
  cancelUploadRetry: (taskId) => request(`/upload/tasks/${encodeURIComponent(taskId)}/cancel-retry`, { method: 'POST' }),
  reprocessMultimodal: (kbName) => invalidateAfter(
    fetchJson(`/kb/${encodeURIComponent(kbName)}/reprocess-multimodal`, { method: 'POST' }),
    kbName,
  ),
  downloadDocumentUrl: (id, kb = currentKB) => {
    const token = getToken()
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : ''
    return `${API_BASE}/knowledge/documents/${encodeURIComponent(id)}/download?kb=${encodeURIComponent(kb)}${tokenParam}`
  },

  // 图像相似度搜索（视觉嵌入：doubao-embedding-vision）
  imageSearch: (file, topK = 10) => {
    if (!currentKB) { console.warn('[api] 跳过 imageSearch：currentKB 未初始化'); return Promise.reject(new Error('知识库未就绪')) }
    return api.imageSearchForKB(currentKB, file, topK)
  },
  imageSearchForKB: (kbName, file, topK = 10) => {
    const fd = new FormData(); fd.append('image', file)
    return fetch(`${API_BASE}/knowledge/image-search?kb=${encodeURIComponent(kbName)}&top_k=${topK}`, {
      method: 'POST', body: fd, headers: authHeaders()
    }).then(r => {
      if (!r.ok) return r.json().then(e => { throw new Error(e.detail || r.statusText) })
      return r.json()
    })
  },

  // 设置接口（仅管理员；使用 fetchJson 避免附加 ?kb= 参数）
  getSettings: () => fetchJson('/settings'),

  // Revisioned personal/platform settings. Provider credentials are never
  // represented in these payloads.
  getPersonalSettings: () => fetchJson('/users/me/settings'),
  getPersonalSettingsOptions: () => fetchJson('/users/me/settings/options'),
  patchPersonalSettings: (section, data) => fetchJson(`/users/me/settings/${encodeURIComponent(section)}`, { method: 'PATCH', body: JSON.stringify(data) }),
  getPlatformSettings: () => fetchJson('/admin/platform'),
  updatePlatformSettings: (data) => fetchJson('/admin/platform', { method: 'PUT', body: JSON.stringify(data) }),
  listModelProfiles: (kind) => fetchJson(`/model-profiles${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`),
  probeModelProfile: (profileId) => fetchJson(`/admin/model-profiles/${encodeURIComponent(profileId)}/probe`, { method: 'POST' }),
  getKBVisionSettings: (kbName) => fetchJson(`/kb/${encodeURIComponent(kbName)}/vision-settings`),
  updateKBVisionSettings: (kbName, data) => fetchJson(`/kb/${encodeURIComponent(kbName)}/vision-settings`, { method: 'PUT', body: JSON.stringify(data) }),
  updateMyProfile: (data) => fetchJson('/auth/me/profile', { method: 'PUT', body: JSON.stringify(data) }),
  updateMyPassword: (data) => fetchJson('/auth/me/password', { method: 'PUT', body: JSON.stringify(data) }),

  // 个人图片理解模型偏好（所有已登录用户）
  listVisionModels: (kind) => fetchJson(`/vision-models${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`),
  getModelPreferences: () => fetchJson('/users/me/model-preferences'),
  updateModelPreferences: (data) => fetchJson('/users/me/model-preferences', { method: 'PUT', body: JSON.stringify(data) }),

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
