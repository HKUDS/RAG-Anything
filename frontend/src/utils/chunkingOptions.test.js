import assert from 'node:assert/strict'
import test from 'node:test'
import {
  canonicalChunkingStrategyId,
  fallbackChunkingStrategyCatalog,
  fallbackParserOptions,
  MINIMAL_CHUNKING_STRATEGY_IDS,
  normalizeChunkingStrategyCatalog,
  resolveChunkingStrategyIds,
  resolveParserOptions,
} from './chunkingOptions.js'

test('canonicalChunkingStrategyId maps legacy fixed to fixed_size', () => {
  assert.equal(canonicalChunkingStrategyId('fixed'), 'fixed_size')
  assert.equal(canonicalChunkingStrategyId('recursive'), 'recursive')
  assert.equal(canonicalChunkingStrategyId('fixed_size'), 'fixed_size')
  assert.equal(canonicalChunkingStrategyId(''), '')
})

test('normalizeChunkingStrategyCatalog converts arrays to id-keyed objects', () => {
  const catalog = normalizeChunkingStrategyCatalog([
    { id: 'recursive', name: 'r', cost_level: 'free' },
    { id: 'fixed', name: 'f' },
  ])
  assert.deepEqual(Object.keys(catalog).sort(), ['fixed_size', 'recursive'])
  assert.equal(catalog.recursive.name, 'r')
  assert.equal(catalog.fixed_size.name, 'f')
  assert.equal(catalog.fixed_size.cost_level, undefined)
})

test('normalizeChunkingStrategyCatalog passes through id-keyed objects', () => {
  const catalog = normalizeChunkingStrategyCatalog({ sentence: { name: 's' }, fixed: { name: 'x' } })
  assert.deepEqual(Object.keys(catalog).sort(), ['fixed_size', 'sentence'])
})

test('fallbackChunkingStrategyCatalog returns the built-in six strategies', () => {
  const catalog = fallbackChunkingStrategyCatalog()
  assert.deepEqual(Object.keys(catalog).sort(), [
    'agentic', 'fixed_size', 'recursive', 'semantic', 'sentence', 'structure',
  ])
})

test('fallbackParserOptions merges the current parser with docling', () => {
  assert.deepEqual(fallbackParserOptions('mineru').map(item => item.id), ['mineru', 'docling'])
  assert.deepEqual(fallbackParserOptions(undefined).map(item => item.id), ['docling'])
  assert.deepEqual(fallbackParserOptions('docling').map(item => item.id), ['docling'])
})

test('MINIMAL_CHUNKING_STRATEGY_IDS exposes the personal-settings fallback', () => {
  assert.deepEqual(MINIMAL_CHUNKING_STRATEGY_IDS, ['recursive', 'fixed_size'])
})

test('resolveParserOptions renders a present catalog as-is and falls back only when missing', () => {
  const catalog = [{ id: 'docling', name: 'docling', available: true }]
  assert.deepEqual(resolveParserOptions(catalog, 'mineru'), catalog)
  assert.deepEqual(resolveParserOptions([], 'mineru'), [])
  assert.deepEqual(resolveParserOptions(undefined, 'mineru').map(item => item.id), ['mineru', 'docling'])
  assert.deepEqual(resolveParserOptions(null, undefined).map(item => item.id), ['docling'])
})

test('resolveChunkingStrategyIds canonicalizes ids and falls back only when missing', () => {
  const catalog = [
    { id: 'recursive', name: 'r' },
    { id: 'fixed', name: 'f' },
    { id: 'sentence', name: 's' },
  ]
  assert.deepEqual(resolveChunkingStrategyIds(catalog), [
    { id: 'recursive', name: 'r' },
    { id: 'fixed_size', name: 'f' },
    { id: 'sentence', name: 's' },
  ])
  assert.deepEqual(resolveChunkingStrategyIds([]), [])
  assert.deepEqual(resolveChunkingStrategyIds(undefined).map(item => item.id), MINIMAL_CHUNKING_STRATEGY_IDS)
})

test('resolveChunkingStrategyIds deduplicates canonical ids', () => {
  const catalog = [{ id: 'fixed', name: 'a' }, { id: 'fixed_size', name: 'b' }]
  assert.deepEqual(resolveChunkingStrategyIds(catalog), [{ id: 'fixed_size', name: 'a' }])
})
