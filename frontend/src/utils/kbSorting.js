const COUNT_FIELD_BY_SORT_FIELD = {
  documents: 'documents',
  entities: 'entities',
}

function compareByName(left, right) {
  return String(left.name || '').localeCompare(String(right.name || ''), 'zh-CN')
}

export function getKnowledgeBaseUpdateTimestamp(kb) {
  return kb.last_updated_at || kb.last_content_updated_at || kb.created || ''
}

function getTimestamp(kb) {
  const timestamp = Date.parse(getKnowledgeBaseUpdateTimestamp(kb))
  return Number.isFinite(timestamp) ? timestamp : null
}

function getCount(kb, kbStats, field) {
  const stats = kbStats[kb.name] ?? kb.stats
  if (!stats || stats.unavailable === true) return null

  const value = Number(stats[field])
  return Number.isFinite(value) ? value : null
}

/** Return a sorted copy without mutating cached API data. */
export function sortKnowledgeBases(kbs, kbStats, sortField, sortDirection) {
  const direction = sortDirection === 'asc' ? 1 : -1
  const countField = COUNT_FIELD_BY_SORT_FIELD[sortField]

  return [...kbs].sort((left, right) => {
    const leftValue = countField
      ? getCount(left, kbStats, countField)
      : getTimestamp(left)
    const rightValue = countField
      ? getCount(right, kbStats, countField)
      : getTimestamp(right)

    if (leftValue === null || rightValue === null) {
      if (leftValue !== rightValue) return leftValue === null ? 1 : -1
      return compareByName(left, right)
    }

    if (leftValue !== rightValue) return (leftValue - rightValue) * direction
    return compareByName(left, right)
  })
}
