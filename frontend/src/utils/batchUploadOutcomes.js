function validFileIndex(value, fileCount) {
  return Number.isInteger(value) && value >= 0 && value < fileCount
}

/**
 * Resolve one batch response against the exact client-side selection order.
 * Older servers omit file_index, so retain the filename-count fallback.
 */
export function resolveBatchUploadOutcomes(pendingFiles, result = {}) {
  const outcomes = new Map()
  const successCounts = new Map()
  const skippedCounts = new Map()
  const errorMessages = new Map()

  const assignIndexed = (items, handler) => {
    for (const item of items || []) {
      if (validFileIndex(item?.file_index, pendingFiles.length)) handler(item.file_index, item)
    }
  }

  assignIndexed(result.tasks, index => outcomes.set(index, { status: 'queued' }))
  assignIndexed(result.skipped_details, index => outcomes.set(index, {
    status: 'skipped', error: '文件重复或注册失败',
  }))
  assignIndexed(result.errors, (index, item) => outcomes.set(index, {
    status: 'failed', error: item.message || '文件提交失败',
  }))

  for (const task of result.tasks || []) {
    if (!validFileIndex(task?.file_index, pendingFiles.length)) {
      successCounts.set(task.filename, (successCounts.get(task.filename) || 0) + 1)
    }
  }
  for (const name of result.skipped || []) {
    skippedCounts.set(name, (skippedCounts.get(name) || 0) + 1)
  }
  for (const item of result.errors || []) {
    if (!validFileIndex(item?.file_index, pendingFiles.length) && item?.filename) {
      const messages = errorMessages.get(item.filename) || []
      messages.push(item.message || '文件提交失败')
      errorMessages.set(item.filename, messages)
    }
  }

  pendingFiles.forEach((file, index) => {
    if (outcomes.has(index)) return
    const queuedCount = successCounts.get(file.name) || 0
    if (queuedCount > 0) {
      successCounts.set(file.name, queuedCount - 1)
      outcomes.set(index, { status: 'queued' })
      return
    }
    const skippedCount = skippedCounts.get(file.name) || 0
    if (skippedCount > 0) {
      skippedCounts.set(file.name, skippedCount - 1)
      outcomes.set(index, { status: 'skipped', error: '文件重复或注册失败' })
      return
    }
    const messages = errorMessages.get(file.name)
    if (messages?.length) {
      outcomes.set(index, { status: 'failed', error: messages.shift() })
    }
  })

  return outcomes
}
