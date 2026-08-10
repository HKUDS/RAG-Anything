import assert from 'node:assert/strict'
import test from 'node:test'
import {
  preferenceNavigationGroups,
  recoverPreferenceSection,
  shouldLoadSettingsOptions,
  visiblePreferenceSections,
} from '../pages/preferencesAccessPolicy.js'

const permissions = values => permission => values.includes(permission)

test('personal settings sections follow capability intersection', () => {
  assert.deepEqual(
    visiblePreferenceSections([], permissions([])),
    ['appearance', 'account', 'security'],
  )
  assert.deepEqual(
    visiblePreferenceSections(['models', 'ingestion', 'retrieval', 'runtime'], permissions(['kb:write'])),
    ['ingestion', 'retrieval', 'runtime', 'appearance', 'account', 'security'],
  )
  assert.deepEqual(
    visiblePreferenceSections(['models', 'ingestion', 'retrieval', 'runtime'], permissions(['kb:write', 'agent:write'])),
    ['models', 'ingestion', 'retrieval', 'runtime', 'appearance', 'account', 'security'],
  )
  assert.deepEqual(
    visiblePreferenceSections(['models', 'ingestion', 'retrieval', 'runtime'], permissions(['agent:write'])),
    ['models', 'appearance', 'account', 'security'],
  )
})

test('all built-in role capability sets expose their intended settings sections', () => {
  const roles = {
    student: [],
    assistant: ['kb:write'],
    teacher: ['kb:write', 'agent:write'],
    dept_admin: ['kb:write', 'agent:write'],
    super_admin: ['kb:write', 'agent:write'],
  }
  const serverSections = ['models', 'ingestion', 'retrieval', 'runtime']
  assert.deepEqual(visiblePreferenceSections(serverSections, permissions(roles.student)), ['appearance', 'account', 'security'])
  assert.deepEqual(visiblePreferenceSections(serverSections, permissions(roles.assistant)), ['ingestion', 'retrieval', 'runtime', 'appearance', 'account', 'security'])
  for (const role of ['teacher', 'dept_admin', 'super_admin']) {
    assert.deepEqual(
      visiblePreferenceSections(serverSections, permissions(roles[role])),
      ['models', 'ingestion', 'retrieval', 'runtime', 'appearance', 'account', 'security'],
    )
  }
})

test('navigation, hash recovery, and options requests stay within visible sections', () => {
  const student = ['appearance', 'account', 'security']
  assert.deepEqual(preferenceNavigationGroups(student), [{ label: '账户与体验', items: student }])
  assert.equal(recoverPreferenceSection('#models', student), 'appearance')
  assert.equal(shouldLoadSettingsOptions(student), false)
  assert.equal(shouldLoadSettingsOptions(['retrieval', ...student]), true)
})
