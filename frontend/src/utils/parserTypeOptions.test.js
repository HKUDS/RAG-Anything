import assert from 'node:assert/strict'
import test from 'node:test'
import {
  fallbackParserOptionsByType,
  formatParsersByType,
  normalizeParsersByType,
  PARSER_FILE_TYPES,
  resolveParserOptionsByType,
  summarizeParsersByType,
} from './parserTypeOptions.js'

const CATALOG = [
  { id: 'docling', name: 'docling', available: true, supported_types: ['pdf', 'office'] },
  { id: 'mineru', name: 'mineru', available: true, supported_types: ['pdf', 'office', 'image'] },
  { id: 'marker', name: 'marker', available: false, supported_types: ['pdf', 'office', 'image'] },
  { id: 'paddleocr', name: 'paddleocr', available: true, supported_types: ['pdf', 'office', 'image'] },
  { id: 'opendataloader', name: 'OpenDataLoader', available: true, supported_types: ['pdf'] },
]

test('PARSER_FILE_TYPES lists the three supported types with display labels', () => {
  assert.deepEqual(PARSER_FILE_TYPES.map(item => item.id), ['pdf', 'office', 'image'])
  assert.equal(PARSER_FILE_TYPES[1].label, '办公文档（docx/pptx/xlsx/html）')
  assert.equal(PARSER_FILE_TYPES[2].label, '图片文件解析（jpg/png/…）')
})

test('resolveParserOptionsByType puts the follow-default entry first', () => {
  const options = resolveParserOptionsByType(CATALOG, 'pdf')
  assert.equal(options[0].id, '')
  assert.equal(options[0].name, '跟随默认（推荐）')
})

test('resolveParserOptionsByType filters by supported_types', () => {
  const officeIds = resolveParserOptionsByType(CATALOG, 'office').map(item => item.id)
  assert.ok(!officeIds.includes('opendataloader'))
  assert.ok(officeIds.includes('docling'))
  assert.ok(officeIds.includes('mineru'))

  const imageIds = resolveParserOptionsByType(CATALOG, 'image').map(item => item.id)
  assert.ok(!imageIds.includes('docling'))
  assert.ok(!imageIds.includes('opendataloader'))
  assert.ok(imageIds.includes('mineru'))
})

test('resolveParserOptionsByType keeps the available flag for disabled parsers', () => {
  const options = resolveParserOptionsByType(CATALOG, 'image')
  const marker = options.find(item => item.id === 'marker')
  assert.equal(marker.available, false)
  const mineru = options.find(item => item.id === 'mineru')
  assert.equal(mineru.available, true)
})

test('resolveParserOptionsByType falls back to follow-default only when the catalog is missing', () => {
  assert.deepEqual(resolveParserOptionsByType(undefined, 'pdf'), [{ id: '', name: '跟随默认（推荐）' }])
  assert.deepEqual(resolveParserOptionsByType(null, 'office'), [{ id: '', name: '跟随默认（推荐）' }])
})

test('fallbackParserOptionsByType returns only the follow-default choice', () => {
  assert.deepEqual(fallbackParserOptionsByType(), [{ id: '', name: '跟随默认（推荐）' }])
})

test('normalizeParsersByType drops empty-string keys and returns a new object', () => {
  const input = { pdf: 'docling', office: '', image: '' }
  const normalized = normalizeParsersByType(input)
  assert.deepEqual(normalized, { pdf: 'docling' })
  assert.notEqual(normalized, input)
})

test('normalizeParsersByType tolerates undefined, null, and empty objects', () => {
  assert.deepEqual(normalizeParsersByType(undefined), {})
  assert.deepEqual(normalizeParsersByType(null), {})
  assert.deepEqual(normalizeParsersByType({}), {})
})

test('normalizeParsersByType drops non-string values', () => {
  assert.deepEqual(normalizeParsersByType({ pdf: 'docling', office: null, image: 7 }), { pdf: 'docling' })
})

test('formatParsersByType renders the saved/effective state summary', () => {
  assert.equal(formatParsersByType({ pdf: 'docling' }), 'PDF: docling / 办公文档: 跟随默认 / 图片文件: 跟随默认')
  assert.equal(formatParsersByType({ image: 'mineru', office: 'paddleocr' }), 'PDF: 跟随默认 / 办公文档: paddleocr / 图片文件: mineru')
})

test('formatParsersByType shows follow-default when the map is missing or empty', () => {
  assert.equal(formatParsersByType(undefined), 'PDF: 跟随默认 / 办公文档: 跟随默认 / 图片文件: 跟随默认')
  assert.equal(formatParsersByType({}), 'PDF: 跟随默认 / 办公文档: 跟随默认 / 图片文件: 跟随默认')
})

test('summarizeParsersByType shows follow-default when nothing is overridden', () => {
  assert.equal(summarizeParsersByType({}), '全部跟随默认')
  assert.equal(summarizeParsersByType(undefined), '全部跟随默认')
  assert.equal(summarizeParsersByType({ pdf: '' }), '全部跟随默认')
})

test('summarizeParsersByType lists overridden types in canonical order', () => {
  assert.equal(summarizeParsersByType({ pdf: 'mineru', office: 'docling' }), '已指定：PDF、办公文档')
})

test('summarizeParsersByType ignores unknown keys', () => {
  assert.equal(summarizeParsersByType({ pdf: 'mineru', unknown: 'docling' }), '已指定：PDF')
})

test('summarizeParsersByType renders a single overridden type', () => {
  assert.equal(summarizeParsersByType({ image: 'mineru' }), '已指定：图片文件')
})
