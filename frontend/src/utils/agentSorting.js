function compareByNameAndId(left, right) {
  const nameComparison = String(left.name || '').localeCompare(String(right.name || ''), 'zh-CN')
  if (nameComparison !== 0) return nameComparison
  return String(left.id || '').localeCompare(String(right.id || ''), 'zh-CN')
}

function getTimestamp(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : null
}

function getConversationCount(agent) {
  const value = agent.conversation_count
  if (value === null || value === undefined || value === '') return null
  const count = Number(value)
  return Number.isFinite(count) ? count : null
}

function getSortValue(agent, sortField) {
  if (sortField === 'conversationCount') return getConversationCount(agent)
  if (sortField === 'lastConversation') return getTimestamp(agent.last_conversation_at)
  return getTimestamp(agent.updated_at)
}

/** Return a sorted copy without mutating API data. */
export function sortAgents(agents, sortField, sortDirection) {
  const direction = sortDirection === 'asc' ? 1 : -1

  return [...agents].sort((left, right) => {
    const leftValue = getSortValue(left, sortField)
    const rightValue = getSortValue(right, sortField)

    if (leftValue === null || rightValue === null) {
      if (leftValue !== rightValue) return leftValue === null ? 1 : -1
      return compareByNameAndId(left, right)
    }

    if (leftValue !== rightValue) return (leftValue - rightValue) * direction
    return compareByNameAndId(left, right)
  })
}
