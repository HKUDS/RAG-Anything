import assert from 'node:assert/strict'
import test from 'node:test'
import { formatDate } from './dateFormat.js'

test('rejects version-number-like values that previously rendered as 2000-01-01', () => {
  assert.equal(formatDate('0'), '')
  assert.equal(formatDate('3'), '')
  assert.equal(formatDate('7'), '')
})

test('formats ISO timestamps as local date and time', () => {
  assert.equal(formatDate('2026-08-03T06:30:00+00:00'), '2026/08/03 14:30')
  assert.equal(formatDate('2026-08-03T14:30:00+08:00'), '2026/08/03 14:30')
})

test('renders the same Beijing instant from naive, +08:00 and UTC inputs', () => {
  // Upload timestamps can arrive as naive local time (in-memory tasks),
  // +08:00 (beijing_now doc_status) or +00:00 (PostgreSQL timestamptz).
  assert.equal(formatDate('2026-08-03T14:30:00'), '2026/08/03 14:30')
  assert.equal(formatDate('2026-08-03T14:30:00+08:00'), '2026/08/03 14:30')
  assert.equal(formatDate('2026-08-03T06:30:00+00:00'), '2026/08/03 14:30')
})

test('returns empty string for missing or invalid input', () => {
  assert.equal(formatDate(''), '')
  assert.equal(formatDate(null), '')
  assert.equal(formatDate(undefined), '')
  assert.equal(formatDate(0), '')
  assert.equal(formatDate('not-a-date'), '')
})
