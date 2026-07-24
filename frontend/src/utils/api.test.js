import assert from 'node:assert/strict'
import test from 'node:test'
import { api } from './api.js'

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
