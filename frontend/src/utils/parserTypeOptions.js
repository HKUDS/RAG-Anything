// Per-file-type parser override helpers for the personal settings page.
// The backend ingestion catalog now carries `supported_types` per parser
// (e.g. opendataloader -> ["pdf"]), so the settings UI can offer only
// parsers that genuinely support the selected file type. A missing catalog
// (options request failed) collapses every per-type selector to the single
// "follow default" choice while remaining editable.

export const PARSER_FILE_TYPES = [
  { id: 'pdf', label: 'PDF' },
  { id: 'office', label: '办公文档（docx/pptx/xlsx/html）' },
  { id: 'image', label: '图片文件解析（jpg/png/…）' },
]

const FOLLOW_DEFAULT_OPTION = { id: '', name: '跟随默认（推荐）' }

// Short labels used by the saved/effective state grid (the dropdown rows use
// the fuller PARSER_FILE_TYPES labels).
const PARSER_TYPE_DISPLAY_LABELS = {
  pdf: 'PDF',
  office: '办公文档',
  image: '图片文件',
}

// Resolve the option list for one per-type parser select. The "follow
// default" entry always comes first, followed by catalog entries whose
// `supported_types` includes the file type. The `available` flag is kept so
// uninstalled parsers can be grayed out.
export function resolveParserOptionsByType(parsers, fileType) {
  const options = [{ ...FOLLOW_DEFAULT_OPTION }]
  if (Array.isArray(parsers)) {
    for (const parser of parsers) {
      if (!parser || !parser.id) continue
      if (!Array.isArray(parser.supported_types) || !parser.supported_types.includes(fileType)) continue
      options.push({
        id: parser.id,
        name: parser.name || parser.id,
        available: parser.available,
      })
    }
  }
  return options
}

// Fallback used when the options request fails: each per-type selector only
// offers "follow default" and stays editable.
export function fallbackParserOptionsByType() {
  return [{ ...FOLLOW_DEFAULT_OPTION }]
}

// Drop empty/blank keys before persisting so "follow default" rows never
// produce pseudo-dirty drafts or empty-string values in storage.
export function normalizeParsersByType(value) {
  if (!value || typeof value !== 'object') return {}
  const normalized = {}
  for (const [fileType, parserId] of Object.entries(value)) {
    if (typeof parserId === 'string' && parserId !== '') normalized[fileType] = parserId
  }
  return normalized
}

// Human-readable summary for the saved/effective state grid, e.g.
// "PDF: docling / 办公文档: 跟随默认 / 图片文件: 跟随默认".
export function formatParsersByType(value) {
  const normalized = normalizeParsersByType(value)
  return PARSER_FILE_TYPES
    .map(({ id }) => `${PARSER_TYPE_DISPLAY_LABELS[id] || id}: ${normalized[id] || '跟随默认'}`)
    .join(' / ')
}

// One-line summary for the collapsed per-file-type override section, e.g.
// "已指定：PDF、办公文档", or "全部跟随默认" when nothing is overridden.
// Iterates PARSER_FILE_TYPES in canonical order so unknown keys are ignored.
export function summarizeParsersByType(parsersByType) {
  const overridden = []
  if (parsersByType && typeof parsersByType === 'object') {
    for (const { id } of PARSER_FILE_TYPES) {
      const value = parsersByType[id]
      if (typeof value === 'string' && value !== '') overridden.push(id)
    }
  }
  return overridden.length === 0 ? '全部跟随默认' : `已指定：${overridden.map(id => PARSER_TYPE_DISPLAY_LABELS[id]).join('、')}`
}
