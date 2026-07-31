const GRAPH_READY_STATES = new Set(['ready', 'completed', 'processed', 'complete'])
const ACTIVE_UPLOAD_TASK_STATUSES = new Set(['queued', 'processing', 'retry_wait'])

export function getDocumentHealth(doc) {
  if (!doc || typeof doc !== 'object') return 'unknown'
  if (doc.health) {
    const health = String(doc.health).toLowerCase()
    if (['healthy', 'ok', 'ready'].includes(health)) return doc.raw_status || doc.status || 'processed'
    return health
  }
  if (doc.status === 'degraded') return 'degraded'

  const graphStatus = String(doc.graph_status || '').toLowerCase()
  if (doc.content_ready === true && graphStatus && !GRAPH_READY_STATES.has(graphStatus)) {
    return 'degraded'
  }

  return doc.raw_status || doc.status || 'unknown'
}

export function isCancellableUploadDocument(doc) {
  if (!doc?.upload_task_id) return false
  return doc.can_cancel_upload === true || ACTIVE_UPLOAD_TASK_STATUSES.has(getDocumentHealth(doc))
}

export function getUploadTaskStatus(task) {
  return task?.outcome === 'degraded' ? 'degraded' : (task?.status || 'queued')
}

export function getUploadTaskMessages(task) {
  const status = getUploadTaskStatus(task)
  const warning = task?.warning_message || task?.warning || ''
  const error = task?.error_message || task?.error || ''

  if (status === 'retry_wait') {
    return {
      warning: `模型服务暂不可用，等待自动重试 ${task?.retry_count || 0}/${task?.max_retries || 5}`,
      error,
    }
  }

  if (status === 'degraded') {
    return {
      warning: warning || error || '文本内容已可用，知识图谱正在等待补偿',
      error: '',
    }
  }

  if (task?.failure_stage === 'ocr') {
    return {
      warning: '页面 OCR 内存不足，处理已停止；未写入不完整文档内容',
      error: error || '请检查失败页或以较低分辨率重新上传该文档',
    }
  }

  return { warning, error }
}
