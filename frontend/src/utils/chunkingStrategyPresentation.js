const STRATEGY_PRESENTATION = {
  fixed_size: {
    name: '按长度切分',
    description: '按固定长度整理内容，适合结构简单的文本。',
    timing: '处理较快',
  },
  recursive: {
    name: '按段落自然切分',
    description: '优先保留段落和句子边界，适合大多数资料。',
    timing: '推荐，处理较快',
  },
  sentence: {
    name: '按完整句子切分',
    description: '尽量不截断句子，适合连续正文。',
    timing: '处理较快',
  },
  structure: {
    name: '按章节结构切分',
    description: '按标题和段落组织内容，适合格式规范的文档。',
    timing: '处理较快',
  },
  semantic: {
    name: '按内容主题切分',
    description: '按相近主题组织内容，适合主题变化较多的资料。',
    timing: '处理时间较长',
  },
  agentic: {
    name: '智能理解后切分',
    description: '自动识别内容结构与主题，适合需要更细致理解的资料。',
    timing: '处理时间最长',
  },
}

export const DEFAULT_CHUNKING_STRATEGY = 'recursive'

export const UNKNOWN_CHUNKING_STRATEGY_NAME = '未识别的切块方式'

export function getChunkingStrategyPresentation(strategy) {
  if (!strategy) {
    return {
      name: '未记录',
      description: '这份历史文档没有保存切块方式。',
      timing: '',
    }
  }

  return STRATEGY_PRESENTATION[strategy] || {
    name: UNKNOWN_CHUNKING_STRATEGY_NAME,
    description: '该文档使用的切块方式无法在当前版本中识别。',
    timing: '',
  }
}

export function getChunkingStrategyOptions(strategies = {}) {
  return Object.keys(STRATEGY_PRESENTATION)
    .filter(key => Object.prototype.hasOwnProperty.call(strategies, key))
    .map(key => ({ id: key, ...STRATEGY_PRESENTATION[key] }))
}
