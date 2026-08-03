import assert from 'node:assert/strict'
import test from 'node:test'
import {
  advanceKnowledgeDetailAuthGeneration,
  api,
  getCurrentKB,
  setCurrentKB,
  streamSSE,
} from './api.js'

test('streams authenticated terminal SSE events without reading past done', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const encoder = new TextEncoder()
  let reads = 0
  let cancelled = false
  globalThis.localStorage = { getItem: () => JSON.stringify({ token: 'token-1' }) }
  let requestHeaders
  globalThis.fetch = async (_url, options) => {
    requestHeaders = options.headers
    return ({
    ok: true,
    status: 200,
    body: { getReader: () => ({
      read: async () => {
        reads += 1
        return reads === 1
          ? { done: false, value: encoder.encode('data: {"type":"done"}\r\n') }
          : { done: true }
      },
      cancel: async () => { cancelled = true },
      releaseLock: () => {},
    }) },
    })
  }
  t.after(() => { globalThis.fetch = originalFetch; globalThis.localStorage = originalLocalStorage })
  const events = []
  await streamSSE('/api/agents/a/query/stream', { body: '{}', onEvent: event => events.push(event) })
  assert.equal(events[0].type, 'done')
  assert.equal(reads, 1)
  assert.equal(cancelled, true)
  assert.equal(requestHeaders.Authorization, 'Bearer token-1')
})

function jsonResponse(value) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify(value),
  }
}

test('loads every tag page with offsets and de-duplicates stable tag ids', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    if (calls.length === 1) {
      return jsonResponse({
        tags: Array.from({ length: 200 }, (_value, index) => ({
          id: index + 1,
          name: `tag-${index + 1}`,
        })),
      })
    }
    return jsonResponse({
      tags: [{ id: 200, name: 'tag-200' }, { id: 201, name: 'tag-201' }],
    })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  const result = await api.listAllKnowledgeTags({ kb: 'demo', query: 'gear' })

  assert.equal(result.tags.length, 201)
  assert.match(calls[0], /limit=200&offset=0$/)
  assert.match(calls[1], /limit=200&offset=200$/)
  assert.match(calls[0], /q=gear/)
})

test('explicit KB detail reads encode the target without changing ambient currentKB', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    return jsonResponse({ documents: [] })
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  setCurrentKB('ambient-kb')
  await api.getDocumentsForKB('目标 KB/2')

  assert.equal(getCurrentKB(), 'ambient-kb')
  assert.equal(calls.length, 1)
  assert.equal(calls[0], '/api/knowledge/documents?kb=%E7%9B%AE%E6%A0%87%20KB%2F2')
})

test('detail prefetch shares in-flight document and statistics requests', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    await Promise.resolve()
    return String(url).includes('/documents')
      ? jsonResponse({ documents: [{ id: 'doc-1' }] })
      : jsonResponse({ documents: 1, entities: 2, relations: 3, chunks: 4 })
  }
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  const first = api.prefetchKnowledgeDetail('manuals')
  const second = api.prefetchKnowledgeDetail('manuals')
  assert.strictEqual(first, second)

  const result = await first
  assert.equal(calls.length, 2)
  assert.equal(result.documents.status, 'ready')
  assert.deepEqual(result.documents.data, [{ id: 'doc-1' }])
  assert.equal(result.stats.data.documents, 1)
})

test('cancelling one detail consumer does not abort or poison the shared prefetch', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const calls = []
  let releaseFetches
  const fetchBarrier = new Promise(resolve => { releaseFetches = resolve })
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    calls.push(String(url))
    await fetchBarrier
    return String(url).includes('/documents')
      ? jsonResponse({ documents: [{ id: 'doc-1' }] })
      : jsonResponse({ documents: 1, entities: 2, relations: 3, chunks: 4 })
  }
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  const controller = new AbortController()
  const cancelledConsumer = api.prefetchKnowledgeDetail('manuals', { signal: controller.signal })
  const survivingConsumer = api.prefetchKnowledgeDetail('manuals')
  controller.abort()
  releaseFetches()

  await assert.rejects(cancelledConsumer, error => error?.name === 'AbortError')
  const result = await survivingConsumer
  assert.equal(calls.length, 2)
  assert.equal(result.documents.status, 'ready')
  assert.equal(api.getCachedKnowledgeDetail('manuals').stats.data.documents, 1)
})

test('authentication generation changes clear the knowledge-base list cache', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  let calls = 0
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async () => {
    calls += 1
    return jsonResponse({ knowledge_bases: [{ name: `kb-${calls}` }] })
  }
  t.after(() => {
    advanceKnowledgeDetailAuthGeneration()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  const first = await api.listKBs({ force: true })
  const cached = await api.listKBs()
  assert.equal(calls, 1)
  assert.deepEqual(cached, first)

  advanceKnowledgeDetailAuthGeneration()
  const nextSession = await api.listKBs()
  assert.equal(calls, 2)
  assert.equal(nextSession.knowledge_bases[0].name, 'kb-2')
})

test('a previous authentication session cannot repopulate or clear the current KB list request', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  const pending = []
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = () => new Promise(resolve => pending.push(resolve))
  t.after(() => {
    advanceKnowledgeDetailAuthGeneration()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  const previousSession = api.listKBs({ force: true })
  assert.equal(pending.length, 1)

  advanceKnowledgeDetailAuthGeneration()
  const currentSession = api.listKBs()
  assert.equal(pending.length, 2)

  pending[1](jsonResponse({ knowledge_bases: [{ name: 'current-kb' }] }))
  const currentResult = await currentSession
  assert.equal(currentResult.knowledge_bases[0].name, 'current-kb')

  pending[0](jsonResponse({ knowledge_bases: [{ name: 'previous-kb' }] }))
  await previousSession

  const cachedCurrentResult = await api.listKBs()
  assert.equal(pending.length, 2)
  assert.equal(cachedCurrentResult.knowledge_bases[0].name, 'current-kb')
})

test('a forbidden detail refresh evicts cached rows and returns fail-closed resources', async t => {
  const originalFetch = globalThis.fetch
  const originalLocalStorage = globalThis.localStorage
  let forbidden = false
  globalThis.localStorage = { getItem: () => null }
  globalThis.fetch = async url => {
    if (forbidden) {
      return {
        ok: false,
        status: 403,
        statusText: 'Forbidden',
        text: async () => JSON.stringify({ detail: 'forbidden' }),
      }
    }
    return String(url).includes('/documents')
      ? jsonResponse({ documents: [{ id: 'doc-1' }] })
      : jsonResponse({ documents: 1 })
  }
  t.after(() => {
    api.clearKnowledgeDetailCache()
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalLocalStorage
  })

  api.clearKnowledgeDetailCache()
  await api.prefetchKnowledgeDetail('manuals')
  assert.equal(api.getCachedKnowledgeDetail('manuals').documents.data.length, 1)

  forbidden = true
  const denied = await api.prefetchKnowledgeDetail('manuals', { force: true })
  assert.equal(denied.documents.failClosed, true)
  assert.equal(denied.stats.failClosed, true)
  assert.equal(api.getCachedKnowledgeDetail('manuals'), null)
})
