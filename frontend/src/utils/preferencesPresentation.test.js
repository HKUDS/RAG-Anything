import test from 'node:test'
import assert from 'node:assert/strict'
import {
  boundedRange,
  findModelProfile,
  mergeSavedSectionDrafts,
  modelProfileSummary,
  modelSettingValueLabel,
  platformReadOnlyState,
  retrievalPresetValues,
  settingValueLabel,
} from '../pages/preferencesPresentation.js'

test('model technical presentation remains secret-free and exposes availability', () => {
  const profile = { id: 'vlm-a', model: 'vision-a', provider: 'openai_compatible', available: false, unavailable_reason: 'not configured', capabilities: ['image'] }
  assert.equal(findModelProfile([profile], 'vlm-a'), profile)
  assert.deepEqual(modelProfileSummary(profile), {
    status: '不可用：not configured',
    technical: { id: 'vlm-a', model: 'vision-a', provider: 'openai_compatible', capabilities: ['image'] },
  })
  assert.equal(JSON.stringify(modelProfileSummary(profile)).includes('api_key'), false)
})

test('model settings show the configured model instead of their internal profile ID', () => {
  const profiles = [{ id: 'legacy-vlm', display_name: '默认图片理解模型 (qwen-vl-plus)', model: 'qwen-vl-plus' }]

  assert.equal(modelSettingValueLabel(profiles, 'legacy-vlm'), 'qwen-vl-plus')
  assert.equal(modelSettingValueLabel(profiles, undefined), '继承')
})

test('named retrieval presets resolve to distinct, reproducible field sets', () => {
  const balanced = retrievalPresetValues('balanced')
  const precise = retrievalPresetValues('precise')
  const broad = retrievalPresetValues('broad')
  assert.ok(balanced)
  assert.ok(precise)
  assert.ok(broad)
  assert.notDeepEqual(balanced, precise)
  assert.notDeepEqual(precise, broad)
  assert.equal(retrievalPresetValues('custom'), null)
})

test('runtime controls use bounded policy values with safe fallbacks', () => {
  assert.deepEqual(boundedRange({ personal_concurrency: 8 }, 'personal_concurrency', 64), { min: 1, max: 8 })
  assert.deepEqual(boundedRange({}, 'llm_timeout', 600), { min: 1, max: 600 })
  assert.deepEqual(boundedRange({}, 'graph_depth', 64, 0), { min: 0, max: 64 })
})

test('typed setting values preserve inheritance state in the UI', () => {
  assert.equal(settingValueLabel(undefined), '继承')
  assert.equal(settingValueLabel(false), '关闭')
  assert.equal(settingValueLabel(['bm25', 'vector']), 'bm25、vector')
})

test('saving one section preserves unsaved drafts in every other section', () => {
  const drafts = {
    models: { llm_profile_id: 'draft-llm' },
    retrieval: { preset: 'custom', graph_depth: 9 },
  }

  assert.deepEqual(
    mergeSavedSectionDrafts(drafts, 'models', {
      models: { llm_profile_id: 'saved-llm' },
      retrieval: { preset: 'balanced' },
    }),
    {
      models: { llm_profile_id: 'saved-llm' },
      retrieval: { preset: 'custom', graph_depth: 9 },
    },
  )
})

test('platform editability combines deployment lock and write permission', () => {
  assert.deepEqual(platformReadOnlyState(false, true), { readOnly: false, reason: null })
  assert.deepEqual(platformReadOnlyState(false, false), { readOnly: true, reason: 'permission' })
  assert.deepEqual(platformReadOnlyState(true, true), { readOnly: true, reason: 'deployment' })
})
