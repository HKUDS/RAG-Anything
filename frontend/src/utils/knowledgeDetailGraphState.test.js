import assert from 'node:assert/strict'
import test from 'node:test'

import {
  GRAPH_DATA_STATUS,
  createGraphDataState,
  graphDataFailed,
  graphDataFromResponses,
  graphDataLoading,
  graphDataSuccess,
} from './knowledgeDetailGraphState.js'

test('state machine starts idle and transitions loading -> ready -> error with retry', () => {
  const idle = createGraphDataState()
  assert.deepEqual(idle, { status: GRAPH_DATA_STATUS.IDLE, error: '' })

  const loading = graphDataLoading(idle)
  assert.equal(loading.status, GRAPH_DATA_STATUS.LOADING)

  assert.deepEqual(graphDataSuccess(loading), { status: GRAPH_DATA_STATUS.READY, error: '' })

  const failed = graphDataFailed(loading, 'network down')
  assert.deepEqual(failed, { status: GRAPH_DATA_STATUS.ERROR, error: 'network down' })

  // error 状态可重新进入 loading（重试）
  assert.equal(graphDataLoading(failed).status, GRAPH_DATA_STATUS.LOADING)
})

test('loading never replaces already-ready data and failures fall back to a default message', () => {
  const ready = { status: GRAPH_DATA_STATUS.READY, error: '' }
  assert.strictEqual(graphDataLoading(ready), ready)
  assert.deepEqual(graphDataFailed(ready, ''), { status: GRAPH_DATA_STATUS.ERROR, error: '图谱数据加载失败' })
})

test('silent refresh failure preserves ready data (preserveReady)', () => {
  const ready = { status: GRAPH_DATA_STATUS.READY, error: '' }
  assert.strictEqual(graphDataFailed(ready, 'boom', { preserveReady: true }), ready)
  const loading = { status: GRAPH_DATA_STATUS.LOADING, error: '' }
  assert.deepEqual(graphDataFailed(loading, 'boom', { preserveReady: true }), {
    status: GRAPH_DATA_STATUS.ERROR,
    error: 'boom',
  })
})

test('graphDataFromResponses normalises entities and precomputes node degree', () => {
  const result = graphDataFromResponses(
    { entities: [{ id: 'e1', name: 'A', type: 'concept' }] },
    {
      nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
      edges: [
        { source: 'a', target: 'b', label: 'x' },
        { source: 'b', target: 'c', label: 'y' },
        { source: 'b', target: 'a', label: 'z' },
      ],
    },
  )
  assert.equal(result.entities.length, 1)
  assert.deepEqual(result.graph.edges, [
    { source: 'a', target: 'b', label: 'x' },
    { source: 'b', target: 'c', label: 'y' },
    { source: 'b', target: 'a', label: 'z' },
  ])
  const byId = Object.fromEntries(result.graph.nodes.map(n => [n.id, n]))
  assert.equal(byId.a.degree, 2)
  assert.equal(byId.b.degree, 3)
  assert.equal(byId.c.degree, 1)
})

test('graphDataFromResponses tolerates missing or empty responses', () => {
  const empty = graphDataFromResponses(undefined, undefined)
  assert.deepEqual(empty, { entities: [], graph: { nodes: [], edges: [] } })
  const partial = graphDataFromResponses({ entities: null }, { nodes: [{ id: 'a' }] })
  assert.deepEqual(partial.entities, [])
  assert.equal(partial.graph.nodes[0].degree, 0)
})
