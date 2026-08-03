import assert from 'node:assert/strict'
import test from 'node:test'

import {
  normalizeAutoRepairKbList,
  rejectAutoRepairKbSelection,
  resolveAutoRepairKbSelection,
  selectConfirmedAutoRepairKb,
} from './autoRepairKbSelection.js'

test('normalizes supported AutoRepair KB list responses without fabricating a fallback', () => {
  assert.deepEqual(normalizeAutoRepairKbList([]), [])
  assert.deepEqual(normalizeAutoRepairKbList({ knowledge_bases: [] }), [])
  assert.deepEqual(normalizeAutoRepairKbList(null), [])
  assert.deepEqual(normalizeAutoRepairKbList({ knowledge_bases: [{ name: 'engine', label: '发动机' }] }), [
    { name: 'engine', label: '发动机' },
  ])
})

test('selects only confirmed AutoRepair KB names', () => {
  const items = [{ name: 'engine', label: '发动机' }, { name: 'brake', label: '制动' }]
  assert.equal(selectConfirmedAutoRepairKb(items, 'brake'), 'brake')
  assert.equal(selectConfirmedAutoRepairKb(items, 'stale'), 'engine')
  assert.equal(selectConfirmedAutoRepairKb([], 'autorepair'), '')
})

test('resolves first render, empty and stale stored selections without a fabricated KB', () => {
  assert.deepEqual(resolveAutoRepairKbSelection({ knowledge_bases: [] }, 'autorepair'), {
    items: [], selected: '', error: null,
  })
  assert.deepEqual(resolveAutoRepairKbSelection({ knowledge_bases: [{ name: 'engine' }] }, 'stale'), {
    items: [{ name: 'engine', label: 'engine' }], selected: 'engine', error: null,
  })
})

test('network and forbidden list failures clear every scoped selection', () => {
  assert.deepEqual(rejectAutoRepairKbSelection(Object.assign(new Error('network down'), { status: 0 })), {
    items: [], selected: '', error: 'network down',
  })
  assert.deepEqual(rejectAutoRepairKbSelection(Object.assign(new Error('forbidden'), { status: 403 })), {
    items: [], selected: '', error: 'forbidden',
  })
})
