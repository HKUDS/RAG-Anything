export function normalizeAutoRepairKbList(response) {
  const source = Array.isArray(response)
    ? response
    : (response && typeof response === 'object' ? response.knowledge_bases || [] : [])
  const seen = new Set()
  return source
    .map(item => typeof item === 'string'
      ? { name: item, label: item }
      : { name: item?.name || item?.label || '', label: item?.label || item?.name || '' })
    .filter(item => {
      if (!item.name || seen.has(item.name)) return false
      seen.add(item.name)
      return true
    })
}

export function selectConfirmedAutoRepairKb(items, preferred = '') {
  if (!Array.isArray(items) || items.length === 0) return ''
  return items.some(item => item.name === preferred) ? preferred : items[0].name
}

export function resolveAutoRepairKbSelection(response, preferred = '') {
  const items = normalizeAutoRepairKbList(response)
  return { items, selected: selectConfirmedAutoRepairKb(items, preferred), error: null }
}

export function rejectAutoRepairKbSelection(error) {
  return {
    items: [],
    selected: '',
    error: error?.message || '知识库列表加载失败',
  }
}
