export const TASK_SETTINGS_SECTIONS = Object.freeze(['models', 'ingestion', 'retrieval', 'runtime'])
export const PREFERENCE_SECTION_ORDER = Object.freeze([
  ...TASK_SETTINGS_SECTIONS,
  'appearance', 'account', 'security',
])

const SECTION_PERMISSION = Object.freeze({
  models: 'agent:write',
  ingestion: 'kb:write',
  retrieval: 'kb:write',
  runtime: 'kb:write',
})

export function localTaskSections(hasPermission) {
  return TASK_SETTINGS_SECTIONS.filter(section => hasPermission?.(SECTION_PERMISSION[section]))
}

export function visiblePreferenceSections(serverSections, hasPermission) {
  const server = new Set(Array.isArray(serverSections) ? serverSections : [])
  const local = new Set(localTaskSections(hasPermission))
  return PREFERENCE_SECTION_ORDER.filter(section => !TASK_SETTINGS_SECTIONS.includes(section) || (server.has(section) && local.has(section)))
}

export function preferenceNavigationGroups(visibleSections) {
  const visible = new Set(visibleSections)
  return [
    { label: '智能与任务', items: TASK_SETTINGS_SECTIONS.filter(section => visible.has(section)) },
    { label: '账户与体验', items: ['appearance', 'account', 'security'].filter(section => visible.has(section)) },
  ].filter(group => group.items.length > 0)
}

export function recoverPreferenceSection(hash, visibleSections) {
  const requested = String(hash || '').replace(/^#/, '')
  return visibleSections.includes(requested) ? requested : (visibleSections[0] || 'appearance')
}

export function shouldLoadSettingsOptions(visibleSections) {
  return visibleSections.some(section => TASK_SETTINGS_SECTIONS.includes(section))
}
