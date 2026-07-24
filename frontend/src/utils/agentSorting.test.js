import assert from 'node:assert/strict'
import test from 'node:test'
import { sortAgents } from './agentSorting.js'

const agents = [
  {
    id: 'agent-b',
    name: 'Beta',
    updated_at: '2026-07-02T00:00:00Z',
    last_conversation_at: '2026-07-05T00:00:00Z',
    conversation_count: 2,
  },
  {
    id: 'agent-a',
    name: 'Alpha',
    updated_at: '2026-07-01T00:00:00Z',
    last_conversation_at: '2026-07-03T00:00:00Z',
    conversation_count: 5,
  },
  {
    id: 'agent-c',
    name: 'Gamma',
    updated_at: '2026-07-03T00:00:00Z',
    conversation_count: 0,
  },
]

test('sorts agent update and last conversation times in both directions', () => {
  assert.deepEqual(
    sortAgents(agents, 'updated', 'desc').map(agent => agent.id),
    ['agent-c', 'agent-b', 'agent-a']
  )
  assert.deepEqual(
    sortAgents(agents, 'lastConversation', 'asc').map(agent => agent.id),
    ['agent-a', 'agent-b', 'agent-c']
  )
})

test('sorts conversation counts in both directions and keeps zero as a known value', () => {
  assert.deepEqual(
    sortAgents(agents, 'conversationCount', 'desc').map(agent => agent.id),
    ['agent-a', 'agent-b', 'agent-c']
  )
  assert.deepEqual(
    sortAgents(agents, 'conversationCount', 'asc').map(agent => agent.id),
    ['agent-c', 'agent-b', 'agent-a']
  )
})

test('keeps unknown activity values last and breaks same-name ties by id', () => {
  const withUnknown = [
    ...agents,
    { id: 'agent-z', name: 'Delta', updated_at: '2026-07-04T00:00:00Z', conversation_count: '' },
    { id: 'agent-2', name: 'Same', updated_at: '2026-07-04T00:00:00Z', conversation_count: 2 },
    { id: 'agent-1', name: 'Same', updated_at: '2026-07-04T00:00:00Z', conversation_count: 2 },
  ]

  const sorted = sortAgents(withUnknown, 'conversationCount', 'desc')
  assert.deepEqual(sorted.map(agent => agent.id), ['agent-a', 'agent-b', 'agent-1', 'agent-2', 'agent-c', 'agent-z'])
  assert.deepEqual(agents.map(agent => agent.id), ['agent-b', 'agent-a', 'agent-c'])
})
