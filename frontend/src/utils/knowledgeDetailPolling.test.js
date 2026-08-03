import assert from 'node:assert/strict'
import test from 'node:test'

import {
  hasActiveUploadTasks,
  isTerminalUploadTask,
  shouldPollCoreData,
  tasksTransitionedToTerminal,
} from './knowledgeDetailPolling.js'

const terminalTasks = [
  { task_id: 't1', status: 'completed' },
  { task_id: 't2', outcome: 'degraded' },
  { task_id: 't3', status: 'failed' },
]
const activeTasks = [
  { task_id: 't4', status: 'queued' },
  { task_id: 't5', status: 'processing' },
  { task_id: 't6', status: 'retry_wait' },
]

test('isTerminalUploadTask treats completed/processed/failed/degraded as terminal', () => {
  assert.equal(isTerminalUploadTask({ status: 'completed' }), true)
  assert.equal(isTerminalUploadTask({ status: 'processed' }), true)
  assert.equal(isTerminalUploadTask({ status: 'failed' }), true)
  assert.equal(isTerminalUploadTask({ outcome: 'degraded' }), true)
  assert.equal(isTerminalUploadTask({ status: 'processing' }), false)
  assert.equal(isTerminalUploadTask({ status: 'queued' }), false)
  assert.equal(isTerminalUploadTask({ status: 'retry_wait' }), false)
  assert.equal(isTerminalUploadTask(null), false)
})

test('hasActiveUploadTasks is false for empty or all-terminal lists', () => {
  assert.equal(hasActiveUploadTasks([]), false)
  assert.equal(hasActiveUploadTasks(terminalTasks), false)
  assert.equal(hasActiveUploadTasks(activeTasks), true)
  assert.equal(hasActiveUploadTasks([...terminalTasks, ...activeTasks]), true)
})

test('shouldPollCoreData requires visible and active uploads', () => {
  assert.equal(shouldPollCoreData({ visible: true, hasActiveUploads: true, activeTab: 'documents' }), true)
  assert.equal(shouldPollCoreData({ visible: true, hasActiveUploads: true, activeTab: 'graph' }), true)
  assert.equal(shouldPollCoreData({ visible: true, hasActiveUploads: false, activeTab: 'documents' }), false)
  assert.equal(shouldPollCoreData({ visible: false, hasActiveUploads: true, activeTab: 'documents' }), false)
  assert.equal(shouldPollCoreData({ visible: false, hasActiveUploads: false, activeTab: 'graph' }), false)
})

test('tasksTransitionedToTerminal only fires on an active -> all-terminal transition', () => {
  assert.equal(tasksTransitionedToTerminal(activeTasks, terminalTasks), true)
  assert.equal(tasksTransitionedToTerminal(activeTasks, []), true)
  assert.equal(tasksTransitionedToTerminal(activeTasks, activeTasks), false)
  assert.equal(tasksTransitionedToTerminal(terminalTasks, terminalTasks), false)
  assert.equal(tasksTransitionedToTerminal(terminalTasks, activeTasks), false)
  assert.equal(tasksTransitionedToTerminal([], []), false)
})
