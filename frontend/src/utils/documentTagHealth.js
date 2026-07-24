const PRESENTATIONS = {
  ready: {
    label: '标签覆盖',
    tone: 'success',
    detail: '所有有语义内容的切块均已关联高置信关键词。',
  },
  not_applicable: {
    label: '无需自动标签',
    tone: 'muted',
    detail: '当前切块仅包含结构、占位或无有效关键词的内容。',
  },
  running: {
    label: '标签生成中',
    tone: 'info',
    detail: '切块已可查看，关键词标签正在后台生成。',
  },
  pending: {
    label: '标签待生成',
    tone: 'info',
    detail: '切块已可查看，系统即将生成关键词标签。',
  },
  retry_wait: {
    label: '标签重试中',
    tone: 'warning',
    detail: '上次生成未完成，系统会自动重试。',
  },
  failed: {
    label: '标签生成失败',
    tone: 'error',
    detail: '切块仍可查看和检索，可重新生成关键词标签。',
  },
  disabled: {
    label: '自动标签已停用',
    tone: 'warning',
    detail: '切块仍可查看，但当前运行设置未启用自动标签。',
  },
  not_started: {
    label: '等待文档入库',
    tone: 'muted',
    detail: '文档入库后将自动生成关键词标签。',
  },
}

const PENDING_STATUSES = new Set(['pending', 'running', 'retry_wait'])

export function getDocumentTagPresentation(document = {}) {
  const status = PRESENTATIONS[document.tag_status]
    ? document.tag_status
    : 'pending'
  const base = PRESENTATIONS[status]
  const tagged = Math.max(0, Number(document.tagged_chunks || 0))
  const eligible = Math.max(0, Number(document.eligible_tag_chunks || 0))
  const notApplicable = Math.max(0, Number(
    document.tag_not_applicable_chunks
      ?? document.not_applicable_tag_chunks
      ?? 0,
  ))
  const uniqueTags = Math.max(0, Number(document.unique_auto_tag_count || 0))
  const assignments = Math.max(0, Number(document.auto_tag_assignment_count || 0))
  const rawAverage = Number(document.avg_auto_tags_per_tagged_chunk || 0)
  const average = Number.isFinite(rawAverage) && rawAverage > 0 ? rawAverage : 0
  const coverage = eligible > 0 ? `${Math.min(tagged, eligible)}/${eligible}` : ''
  const coverageLabel = coverage ? `${coverage} 个有效切块` : ''
  const headline = coverageLabel ? `${base.label} ${coverageLabel}` : base.label
  const densityParts = []
  if (uniqueTags > 0) densityParts.push(`${uniqueTags}个标签词`)
  if (assignments > 0) densityParts.push(`${assignments}次关联`)
  if (average > 0) densityParts.push(`平均${average.toFixed(1)}个标签每有效切块`)
  if (notApplicable > 0) densityParts.push(`${notApplicable}个切块无需标签`)
  return {
    ...base,
    status,
    tagged,
    eligible,
    notApplicable,
    uniqueTags,
    assignments,
    average,
    coverage,
    coverageLabel,
    headline,
    densitySummary: densityParts.join(' · '),
    isPending: PENDING_STATUSES.has(status),
    canRetry: status === 'failed' || status === 'retry_wait',
  }
}
