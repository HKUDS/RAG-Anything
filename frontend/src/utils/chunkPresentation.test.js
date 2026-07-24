import assert from 'node:assert/strict'
import test from 'node:test'
import { detectChunkType, getChunkPresentation, summarizeChunkContent } from './chunkPresentation.js'

test('detects chunk type from structured metadata before content fallback', () => {
  assert.equal(detectChunkType({ original_type: 'IMAGE', content: 'Table Analysis: data' }), 'image')
  assert.equal(detectChunkType({ content: 'Table Analysis: data' }), 'table')
  assert.equal(detectChunkType({ content: 'ordinary text' }), 'text')
})

for (const [type, prefix] of [
  ['image', 'Image'],
  ['table', 'Table'],
  ['equation', 'Mathematical Equation'],
  ['video', 'Video'],
]) {
  test(`detects ${type} analysis prefixes with and without content`, () => {
    assert.equal(detectChunkType({ content: `${prefix} Analysis: useful text` }), type)
    assert.equal(detectChunkType({ content: `${prefix} Content Analysis: useful text` }), type)
  })
}

test('removes multimodal analysis boilerplate while preserving meaningful text', () => {
  assert.equal(
    summarizeChunkContent('Image Content Analysis: - Section Path: None - Neighbor Text: None - Caption: A campus entrance'),
    'Caption: A campus entrance'
  )
})

test('falls back to the original content when cleanup would remove everything', () => {
  assert.equal(
    summarizeChunkContent('Table Analysis: Caption: None - Section Path: None'),
    'Table Analysis: Caption: None - Section Path: None'
  )
})

test('limits long previews without changing short content', () => {
  assert.equal(summarizeChunkContent('  short\ncontent  '), 'short content')
  assert.equal(summarizeChunkContent('a'.repeat(8), 5), 'aaaaa...')
})

test('supports table prefixes without the optional content word', () => {
  assert.equal(
    summarizeChunkContent('TABLE ANALYSIS: Caption: None - The table compares four models.'),
    'The table compares four models.'
  )
})

test('returns an empty preview for empty values', () => {
  assert.equal(summarizeChunkContent('   '), '')
  assert.equal(summarizeChunkContent(null), '')
})

test('does not rewrite ordinary prose that contains analysis field words', () => {
  assert.equal(
    summarizeChunkContent('Clinical analysis: none of the patients improved. The caption: None is quoted.'),
    'Clinical analysis: none of the patients improved. The caption: None is quoted.'
  )
})

test('builds a complete card presentation without changing source content', () => {
  const chunk = {
    content: 'Video Analysis: Caption: None - A teacher explains the diagram.',
    is_multimodal: true,
  }

  assert.deepEqual(getChunkPresentation(chunk), {
    type: 'video',
    typeLabel: '视频',
    hasMedia: true,
    summary: 'A teacher explains the diagram.',
  })
  assert.equal(chunk.content, 'Video Analysis: Caption: None - A teacher explains the diagram.')
})

test('labels untyped multimodal chunks without treating text as a media type', () => {
  assert.equal(getChunkPresentation({ content: 'ordinary text' }).typeLabel, '文本')
  assert.deepEqual(getChunkPresentation({ content: 'ordinary text', is_multimodal: true }), {
    type: 'text',
    typeLabel: '多模态',
    hasMedia: true,
    summary: 'ordinary text',
  })
})
