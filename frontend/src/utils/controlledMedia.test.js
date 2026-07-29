import assert from 'node:assert/strict'
import test from 'node:test'

import { controlledMediaUrl, publicMediaUrl } from './controlledMedia.js'

test('builds only the fixed same-origin media-id route', () => {
  assert.equal(
    controlledMediaUrl({ media_id: 'abcdef0123456789', kb: 'kb&scope' }),
    '/api/knowledge/media/abcdef0123456789?kb=kb%26scope',
  )
  assert.equal(controlledMediaUrl({ media_id: '../../secret', kb: 'kb' }), '')
  assert.equal(controlledMediaUrl({ media_id: 'abcdef0123456789' }), '')
})

test('builds a legacy URL only from an opaque grant and KB', () => {
  const grant = `abcdefghijklmnopqrstuvwx.${'a'.repeat(64)}`
  assert.equal(
    controlledMediaUrl({ legacy_grant: grant, kb: 'legacy-kb' }),
    `/api/knowledge/media/legacy/${grant}?kb=legacy-kb`,
  )
  assert.equal(controlledMediaUrl({ legacy_grant: 'C:/private/image.png', kb: 'legacy-kb' }), '')
})

test('never treats data, local paths, or same-origin arbitrary paths as public media', () => {
  assert.equal(publicMediaUrl({ media_url: 'data:image/png;base64,abc' }), '')
  assert.equal(publicMediaUrl({ media_url: 'C:\\private\\image.png' }), '')
  assert.equal(publicMediaUrl({ media_url: '/api/files/image?path=secret' }), '')
  assert.equal(publicMediaUrl({ media_url: 'https://cdn.example.test/image.png' }), 'https://cdn.example.test/image.png')
  assert.equal(publicMediaUrl({ media_id: 'abcdef0123456789', media_url: 'https://cdn.example.test/image.png' }), '')
})
