import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveBatchUploadOutcomes } from './batchUploadOutcomes.js'

test('maps mixed batch results to their source order when names are duplicated', () => {
  const files = [{ name: 'lesson.mp4' }, { name: 'lesson.mp4' }]
  const results = resolveBatchUploadOutcomes(files, {
    tasks: [{ filename: 'lesson.mp4', file_index: 1 }],
    errors: [{ filename: 'lesson.mp4', file_index: 0, message: '无法创建任务设置快照' }],
  })

  assert.deepEqual(results.get(0), { status: 'failed', error: '无法创建任务设置快照' })
  assert.deepEqual(results.get(1), { status: 'queued' })
})

test('uses filename counts with servers that do not return file indexes', () => {
  const files = [{ name: 'first.mp4' }, { name: 'second.mp4' }]
  const results = resolveBatchUploadOutcomes(files, {
    tasks: [{ filename: 'second.mp4' }],
    errors: [{ filename: 'first.mp4', message: '无法创建任务设置快照' }],
  })

  assert.deepEqual([...results.entries()], [
    [0, { status: 'failed', error: '无法创建任务设置快照' }],
    [1, { status: 'queued' }],
  ])
})
