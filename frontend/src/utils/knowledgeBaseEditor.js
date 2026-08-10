export function getKnowledgeBaseEditCapabilities(kb) {
  const capabilities = kb?.capabilities || {}
  return {
    rename: capabilities.rename === true,
    manageMembers: capabilities.manage_members === true,
  }
}

export function canEditKnowledgeBase(kb) {
  const capabilities = getKnowledgeBaseEditCapabilities(kb)
  return capabilities.rename || capabilities.manageMembers
}

export function getKnowledgeBaseEditorTabs(kb) {
  const capabilities = getKnowledgeBaseEditCapabilities(kb)
  return [
    capabilities.rename && { id: 'details', label: '基本信息' },
    capabilities.manageMembers && { id: 'members', label: '成员与权限' },
  ].filter(Boolean)
}
