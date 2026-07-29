export const DETAIL_RESOURCE_STATUS = Object.freeze({
  LOADING: 'loading',
  READY: 'ready',
  ERROR: 'error',
})

function normaliseResource(resource, fallbackData) {
  if (resource?.status === DETAIL_RESOURCE_STATUS.READY) {
    return {
      status: DETAIL_RESOURCE_STATUS.READY,
      data: resource.data ?? fallbackData,
      error: '',
      refreshing: false,
      refreshError: '',
    }
  }
  if (resource?.status === DETAIL_RESOURCE_STATUS.ERROR) {
    return {
      status: DETAIL_RESOURCE_STATUS.ERROR,
      data: fallbackData,
      error: resource.error || '加载失败，请重试',
      refreshing: false,
      refreshError: '',
    }
  }
  return {
    status: DETAIL_RESOURCE_STATUS.LOADING,
    data: fallbackData,
    error: '',
    refreshing: false,
    refreshError: '',
  }
}

export function createKnowledgeDetailState(kbName, snapshot = null) {
  return {
    kbName,
    documents: normaliseResource(snapshot?.documents, []),
    stats: normaliseResource(snapshot?.stats, {}),
  }
}

export function markKnowledgeDetailRefreshing(state) {
  return {
    ...state,
    documents: {
      ...state.documents,
      refreshing: state.documents.status === DETAIL_RESOURCE_STATUS.READY,
      refreshError: '',
    },
    stats: {
      ...state.stats,
      refreshing: state.stats.status === DETAIL_RESOURCE_STATUS.READY,
      refreshError: '',
    },
  }
}

export function mergeKnowledgeDetailSnapshot(previous, kbName, snapshot) {
  const base = previous?.kbName === kbName
    ? previous
    : createKnowledgeDetailState(kbName)

  const mergeResource = (current, incoming, fallbackData) => {
    if (incoming?.status === DETAIL_RESOURCE_STATUS.READY) {
      return {
        status: DETAIL_RESOURCE_STATUS.READY,
        data: incoming.data ?? fallbackData,
        error: '',
        refreshing: false,
        refreshError: '',
      }
    }
    if (incoming?.failClosed) {
      return {
        status: DETAIL_RESOURCE_STATUS.ERROR,
        data: fallbackData,
        error: incoming.error || '无权访问该知识库',
        refreshing: false,
        refreshError: '',
      }
    }
    if (current.status === DETAIL_RESOURCE_STATUS.READY) {
      return {
        ...current,
        refreshing: false,
        refreshError: incoming?.error || '刷新失败，已保留上次数据',
      }
    }
    return {
      status: DETAIL_RESOURCE_STATUS.ERROR,
      data: fallbackData,
      error: incoming?.error || '加载失败，请重试',
      refreshing: false,
      refreshError: '',
    }
  }

  return {
    kbName,
    documents: mergeResource(base.documents, snapshot?.documents, []),
    stats: mergeResource(base.stats, snapshot?.stats, {}),
  }
}

export function getDocumentListMode({ routeKB, state, filteredCount, hasFilter = false }) {
  if (!state || state.kbName !== routeKB || state.documents.status === DETAIL_RESOURCE_STATUS.LOADING) {
    return 'loading'
  }
  if (state.documents.status === DETAIL_RESOURCE_STATUS.ERROR) return 'error'
  if (filteredCount > 0) return 'ready'
  return hasFilter && state.documents.data.length > 0 ? 'no-match' : 'empty'
}

export function createLatestRequestGate() {
  let current = 0
  return {
    begin() {
      current += 1
      return current
    },
    isLatest(requestId) {
      return requestId === current
    },
    invalidate() {
      current += 1
    },
  }
}
