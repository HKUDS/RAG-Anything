export function findModelProfile(profiles, profileId) {
  return (profiles || []).find(profile => profile.id === profileId) || null
}

export function modelSettingValueLabel(profiles, value) {
  const profile = findModelProfile(profiles, value)
  return profile?.model || settingValueLabel(value)
}

export function modelProfileSummary(profile) {
  if (!profile) return { status: '继承平台默认', technical: null }
  return {
    status: profile.available ? '可用' : `不可用：${profile.unavailable_reason || '服务端配置不完整'}`,
    technical: {
      id: profile.id,
      model: profile.model || '未声明',
      provider: profile.provider || '未声明',
      capabilities: Array.isArray(profile.capabilities) ? profile.capabilities : [],
    },
  }
}

export function boundedRange(limits, field, fallback, minimum = 1) {
  const maximum = Number(limits?.[field])
  return {
    min: minimum,
    max: Number.isFinite(maximum) && maximum > 0 ? maximum : fallback,
  }
}

export function settingValueLabel(value) {
  if (value === undefined) return '继承'
  if (value === null) return '未设置'
  if (typeof value === 'boolean') return value ? '开启' : '关闭'
  if (Array.isArray(value)) return value.length ? value.join('、') : '空列表'
  return String(value)
}

// Presets are concrete, versioned retrieval choices. Keeping the complete
// field set here means the UI saves a reproducible selection instead of an
// inert display label.
export const RETRIEVAL_PRESETS = {
  balanced: {
    rrf_k: 60, bm25_top_k: 50, vector_top_k: 100, graph_top_k: 30,
    graph_depth: 2, channels: ['bm25', 'vector', 'graph'],
    bm25_tokenizer: 'jieba', bm25_k1: 1.5, bm25_b: 0.75,
  },
  precise: {
    rrf_k: 60, bm25_top_k: 30, vector_top_k: 60, graph_top_k: 15,
    graph_depth: 1, channels: ['bm25', 'vector'],
    bm25_tokenizer: 'jieba', bm25_k1: 1.5, bm25_b: 0.75,
  },
  broad: {
    rrf_k: 60, bm25_top_k: 100, vector_top_k: 200, graph_top_k: 60,
    graph_depth: 3, channels: ['bm25', 'vector', 'graph'],
    bm25_tokenizer: 'jieba', bm25_k1: 1.5, bm25_b: 0.75,
  },
}

export function retrievalPresetValues(preset) {
  return RETRIEVAL_PRESETS[preset] || null
}

export function mergeSavedSectionDrafts(currentDrafts, section, stored) {
  return { ...(currentDrafts || {}), [section]: stored?.[section] || {} }
}

export function platformReadOnlyState(policyReadOnly, canWrite) {
  return {
    readOnly: Boolean(policyReadOnly) || !canWrite,
    reason: policyReadOnly ? 'deployment' : canWrite ? null : 'permission',
  }
}
