export function getKnowledgeBaseItems(response) {
  return Array.isArray(response?.knowledge_bases) ? response.knowledge_bases : []
}

export function isKnowledgeBaseConfirmed(response, kbName) {
  if (!kbName) return false
  return getKnowledgeBaseItems(response).some(item => item?.name === kbName)
}
