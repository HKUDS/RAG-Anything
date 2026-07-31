import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getDocumentHealth,
  getUploadTaskMessages,
  getUploadTaskStatus,
  isCancellableUploadDocument,
} from './documentHealth.js'

test('uses API health as the application-level document status', () => {
  assert.equal(getDocumentHealth({ status: 'failed', raw_status: 'failed', health: 'degraded' }), 'degraded')
  assert.equal(getDocumentHealth({ status: 'processed', health: 'healthy' }), 'processed')
})

test('derives degraded for legacy content-ready responses with incomplete graph work', () => {
  assert.equal(getDocumentHealth({ status: 'failed', content_ready: true, graph_status: 'pending' }), 'degraded')
})

test('does not hide a hard failure without verified content', () => {
  assert.equal(getDocumentHealth({ raw_status: 'failed', graph_status: 'failed' }), 'failed')
})

test('presents degraded upload outcomes as degraded completed work', () => {
  assert.equal(getUploadTaskStatus({ status: 'completed', outcome: 'degraded' }), 'degraded')
  assert.equal(getUploadTaskStatus({ status: 'completed', outcome: 'success' }), 'completed')
})

test('routes only explicit active upload task provenance to cancellation', () => {
  for (const status of ['queued', 'processing', 'retry_wait']) {
    assert.equal(
      isCancellableUploadDocument({ upload_task_id: 'task-1', status, can_cancel_upload: false }),
      true,
    )
  }
  assert.equal(isCancellableUploadDocument({ status: 'processing', can_cancel_upload: true }), false)
  assert.equal(isCancellableUploadDocument({ upload_task_id: 'task-1', status: 'completed' }), false)
  assert.equal(isCancellableUploadDocument({ upload_task_id: 'task-1', status: 'failed' }), false)
  assert.equal(isCancellableUploadDocument({ upload_task_id: 'task-1', status: 'degraded' }), false)
  assert.equal(isCancellableUploadDocument({ upload_task_id: 'task-1', status: 'cancelling' }), false)
  assert.equal(isCancellableUploadDocument({ upload_task_id: 'task-1', status: 'completed', can_cancel_upload: true }), true)
})

test('normalizes upload warning fields and does not render degraded work as an error', () => {
  assert.deepEqual(
    getUploadTaskMessages({ status: 'completed', outcome: 'degraded', warning: '图谱待补全' }),
    { warning: '图谱待补全', error: '' },
  )
  assert.deepEqual(
    getUploadTaskMessages({ status: 'completed', outcome: 'degraded', error_message: 'LLM 超时' }),
    { warning: 'LLM 超时', error: '' },
  )
  assert.deepEqual(
    getUploadTaskMessages({ status: 'failed', error: '解析失败' }),
    { warning: '', error: '解析失败' },
  )
  assert.deepEqual(
    getUploadTaskMessages({ status: 'failed', failure_stage: 'ocr', error: 'bad allocation' }),
    {
      warning: '页面 OCR 内存不足，处理已停止；未写入不完整文档内容',
      error: 'bad allocation',
    },
  )
})
