// 图谱/实体数据的按需加载状态机。
// 状态流转：idle -> loading -> ready | error；切走标签不重置；
// error 状态可通过重试按钮重新进入 loading；后台静默刷新失败时保留已有 ready 数据。
export const GRAPH_DATA_STATUS = Object.freeze({
  IDLE: 'idle',
  LOADING: 'loading',
  READY: 'ready',
  ERROR: 'error',
})

export function createGraphDataState() {
  return { status: GRAPH_DATA_STATUS.IDLE, error: '' }
}

// 进入加载态：已就绪的数据不被骨架覆盖（仅用于非静默的首次加载与重试）。
export function graphDataLoading(state) {
  return state?.status === GRAPH_DATA_STATUS.READY
    ? state
    : { status: GRAPH_DATA_STATUS.LOADING, error: '' }
}

export function graphDataSuccess() {
  return { status: GRAPH_DATA_STATUS.READY, error: '' }
}

// 失败态：preserveReady=true（静默刷新）时若已有就绪数据则保留，不闪错误。
export function graphDataFailed(state, error, { preserveReady = false } = {}) {
  if (preserveReady && state?.status === GRAPH_DATA_STATUS.READY) return state
  return { status: GRAPH_DATA_STATUS.ERROR, error: error || '图谱数据加载失败' }
}

// 将接口响应归一化为页面使用的 { entities, graph } 结构，
// 并预计算节点度（与旧实现逐位一致）。
export function graphDataFromResponses(entitiesResponse, graphResponse) {
  const degree = {}
  ;(graphResponse?.edges || []).forEach(edge => {
    degree[edge.source] = (degree[edge.source] || 0) + 1
    degree[edge.target] = (degree[edge.target] || 0) + 1
  })
  return {
    entities: entitiesResponse?.entities || [],
    graph: {
      nodes: (graphResponse?.nodes || []).map(node => ({ ...node, degree: degree[node.id] || 0 })),
      edges: graphResponse?.edges || [],
    },
  }
}
