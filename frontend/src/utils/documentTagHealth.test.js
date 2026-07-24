import assert from 'node:assert/strict'
import test from 'node:test'
import { getDocumentTagPresentation } from './documentTagHealth.js'

test('reports verified coverage without exceeding eligible chunks', () => {
  const result = getDocumentTagPresentation({
    tag_status: 'ready',
    tagged_chunks: 14,
    eligible_tag_chunks: 12,
    tag_not_applicable_chunks: 43,
    unique_auto_tag_count: 87,
    auto_tag_assignment_count: 120,
    avg_auto_tags_per_tagged_chunk: 3,
  })
  assert.equal(result.label, '标签覆盖')
  assert.equal(result.coverage, '12/12')
  assert.equal(result.coverageLabel, '12/12 个有效切块')
  assert.equal(result.headline, '标签覆盖 12/12 个有效切块')
  assert.equal(result.densitySummary, '87个标签词 · 120次关联 · 平均3.0个标签每有效切块 · 43个切块无需标签')
  assert.equal(result.isPending, false)
})

test('omits unavailable density metrics without inventing zero-value claims', () => {
  const result = getDocumentTagPresentation({
    tag_status: 'not_applicable', not_applicable_tag_chunks: 5,
  })
  assert.equal(result.headline, '无需自动标签')
  assert.equal(result.densitySummary, '5个切块无需标签')
})

test('keeps retry states visibly pending and actionable', () => {
  const result = getDocumentTagPresentation({ tag_status: 'retry_wait' })
  assert.equal(result.isPending, true)
  assert.equal(result.canRetry, true)
  assert.equal(result.tone, 'warning')
})

test('treats an unknown or missing status as pending', () => {
  assert.equal(getDocumentTagPresentation({}).status, 'pending')
})
