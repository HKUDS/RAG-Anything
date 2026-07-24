const ANALYSIS_PREFIX = /^(image|table|mathematical equation|video)(?:\s+content)?\s+analysis\s*:\s*/i

const EMPTY_ANALYSIS_FIELDS = /\b(?:caption|section\s+path|neighbor\s+text|footnotes|analysis)\s*:\s*(?:none|null|n\/a)\b\s*[:;,.\-]?/gi

const TYPE_ALIASES = {
  image: 'image',
  table: 'table',
  'mathematical equation': 'equation',
  equation: 'equation',
  video: 'video',
}

const TYPE_LABELS = {
  text: '文本',
  image: '图片',
  table: '表格',
  equation: '公式',
  video: '视频',
  multimodal: '多模态',
}

function collapseWhitespace(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

export function detectChunkType(chunk) {
  const originalType = collapseWhitespace(chunk?.original_type).toLowerCase()
  if (TYPE_ALIASES[originalType]) return TYPE_ALIASES[originalType]

  const analysisMatch = collapseWhitespace(chunk?.content).match(ANALYSIS_PREFIX)
  return TYPE_ALIASES[analysisMatch?.[1]?.toLowerCase()] || 'text'
}

export function summarizeChunkContent(content, maxLength = 420) {
  const original = collapseWhitespace(content)
  if (!original) return ''

  const cleaned = ANALYSIS_PREFIX.test(original)
    ? collapseWhitespace(
        original
          .replace(ANALYSIS_PREFIX, '')
          .replace(EMPTY_ANALYSIS_FIELDS, '')
          .replace(/^[\s:;,.\-|]+/, '')
      )
    : original
  const preview = cleaned || original
  return preview.length > maxLength ? `${preview.slice(0, maxLength)}...` : preview
}

export function getChunkPresentation(chunk) {
  const type = detectChunkType(chunk)
  const hasMedia = type !== 'text' || Boolean(chunk?.is_multimodal)
  const displayType = type === 'text' && hasMedia ? 'multimodal' : type

  return {
    type,
    typeLabel: TYPE_LABELS[displayType],
    hasMedia,
    summary: summarizeChunkContent(chunk?.content),
  }
}
