import { useState, useEffect } from 'react'
import { Save, Trash2, TestTube2, Cpu, Sliders, Scissors, AlertCircle } from 'lucide-react'
import { api } from '../utils/api'

export default function SettingsPage({ onToast }) {
  const [settings, setSettings] = useState({})
  const [local, setLocal] = useState({})
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    api.getSettings().then(s => { setSettings(s); setLocal(s) }).catch(() => {})
  }, [])

  const save = async (partial) => {
    try {
      await api.updateSettings(partial)
      setSettings(prev => ({ ...prev, ...partial }))
      onToast?.('设置已更新 ✨', 'success')
    } catch (e) { onToast?.(e.message, 'error') }
  }

  const testConnection = async () => {
    setTesting(true)
    try {
      await api.health()
      onToast?.('API 连接正常 ✅', 'success')
    } catch (e) {
      onToast?.(`连接失败: ${e.message}`, 'error')
    }
    setTesting(false)
  }

  return (
    <div className="max-w-2xl space-y-8">
      <div className="page-header page-header-divider">
        <div>
          <h2 className="page-title">⚙️ 系统设置</h2>
          <p className="page-subtitle">配置解析器、模型和处理参数</p>
        </div>
      </div>

      {/* Parser */}
      <div className="card p-5 space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-medium text-warm-700"><Cpu size={16}/>解析器</h3>
        <select className="input-field"
          value={local.parser || 'docling'}
          onChange={e => { setLocal({ ...local, parser: e.target.value }); save({ parser: e.target.value }) }}>
          <option value="docling">Docling（推荐）</option>
          <option value="mineru">MinerU</option>
          <option value="paddleocr">PaddleOCR</option>
          <option value="marker">Marker</option>
        </select>
      </div>

      {/* Entity Extraction */}
      <div className="card p-5 space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-medium text-warm-700"><Sliders size={16}/>实体抽取</h3>
        <div>
          <label className="text-xs text-warm-500">实体类型白名单（逗号分隔，留空=默认）</label>
          <input className="input-field text-sm mt-1" type="text"
            placeholder="如：Part,Process,Material"
            value={local.entity_types || ''}
            onChange={e => { setLocal({ ...local, entity_types: e.target.value }); save({ entity_types: e.target.value }) }} />
        </div>
        <div>
          <label className="text-xs text-warm-500">最小连通度（0=不过滤, 1=移除孤立实体）</label>
          <input className="input-field text-sm mt-1" type="number" min="0" max="10"
            value={local.entity_extraction_min_degree ?? 0}
            onChange={e => { const v = parseInt(e.target.value) || 0; setLocal({ ...local, entity_extraction_min_degree: v }); save({ entity_extraction_min_degree: v }) }} />
        </div>
      </div>

      {/* Models */}
      <div className="card p-5 space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-medium text-warm-700"><TestTube2 size={16}/>模型配置</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-warm-500">LLM 模型</label>
            <input className="input-field text-sm mt-1" value={local.llm_model || ''} readOnly />
          </div>
          <div>
            <label className="text-xs text-warm-500">Vision 模型</label>
            <input className="input-field text-sm mt-1" value={local.vision_model || ''} readOnly />
          </div>
          <div>
            <label className="text-xs text-warm-500">Embedding 模型</label>
            <input className="input-field text-sm mt-1" value={local.embedding_model || ''} readOnly />
          </div>
          <div>
            <label className="text-xs text-warm-500">Embedding 维度</label>
            <input className="input-field text-sm mt-1" value={local.embedding_dim || ''} readOnly />
          </div>
        </div>
        <button className="btn-secondary text-sm flex items-center gap-2" onClick={testConnection} disabled={testing}>
          {testing ? '测试中…' : '🔌 测试 API 连接'}
        </button>
      </div>

      {/* Chunk + Concurrency */}
      <div className="card p-5 space-y-4">
        <h3 className="flex items-center gap-2 text-sm font-medium text-warm-700"><Sliders size={16}/>处理参数</h3>
        <div>
          <div className="flex justify-between text-sm">
            <span className="text-warm-500">切块大小</span>
            <span className="font-mono text-coral-500 font-medium">{local.chunk_size || 1200} tokens</span>
          </div>
          <input type="range" min="200" max="4000" step="200"
            value={local.chunk_size || 1200}
            onChange={e => { const v = e.target.value; setLocal({ ...local, chunk_size: v }) }}
            onMouseUp={() => save({ chunk_size: parseInt(local.chunk_size) })}
            className="w-full mt-2 accent-coral-500" />
        </div>
        <div>
          <div className="flex justify-between text-sm">
            <span className="text-warm-500">LLM 并发数</span>
            <span className="font-mono text-coral-500 font-medium">{local.llm_max_async || 4}</span>
          </div>
          <input type="range" min="1" max="8" step="1"
            value={local.llm_max_async || 4}
            onChange={e => { const v = e.target.value; setLocal({ ...local, llm_max_async: v }) }}
            onMouseUp={() => save({ max_async: parseInt(local.llm_max_async) })}
            className="w-full mt-2 accent-coral-500" />
        </div>
      </div>

      {/* Chunking Strategy */}
      <div className="card p-5 space-y-4">
        <h3 className="flex items-center gap-2 text-sm font-medium text-warm-700"><Scissors size={16}/>文本分块策略</h3>
        <p className="text-xs text-warm-500">选择文本切割方式，不同策略影响检索精度和处理成本</p>
        <div className="space-y-2">
          {local.chunking_strategies && Object.entries(local.chunking_strategies).map(([key, meta]) => {
            const isActive = (local.chunking_strategy || 'recursive') === key
            const costColors = {
              free: 'text-sage-600 bg-sage-50 border-sage-200',
              medium: 'text-amber-600 bg-amber-50 border-amber-200',
              high: 'text-rose-600 bg-rose-50 border-rose-200',
            }
            return (
              <button key={key}
                onClick={() => {
                  setLocal({ ...local, chunking_strategy: key })
                  save({ chunking_strategy: key })
                }}
                className={`w-full text-left p-3 rounded-xl border transition-all ${
                  isActive
                    ? 'border-coral-300 bg-coral-50/50 shadow-warm-sm'
                    : 'border-warm-200 bg-warm-50 hover:border-warm-300'
                }`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-medium ${isActive ? 'text-coral-600' : 'text-warm-700'}`}>
                        {meta.name}
                      </span>
                      {isActive && <span className="text-[10px] px-1.5 py-0.5 rounded-lg bg-coral-100 text-coral-600 font-mono">当前</span>}
                    </div>
                    <p className="text-xs text-warm-500 mt-0.5">{meta.description}</p>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border shrink-0 ${costColors[meta.cost_level] || costColors.free}`}>
                    {meta.cost}
                  </span>
                </div>
              </button>
            )
          })}
        </div>
        <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-50 border border-amber-200">
          <AlertCircle size={14} className="text-amber-500 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700">
            切换分块策略后，<strong>新上传的文档</strong>将使用新策略处理。已处理的文档不受影响。如需对已有文档重新分块，请先删除后重新上传。
          </p>
        </div>
      </div>

      {/* Cache */}
      <div className="card p-5">
        <h3 className="flex items-center gap-2 text-sm font-medium text-warm-700 mb-3"><Trash2 size={16}/>缓存管理</h3>
        <button className="btn-secondary text-sm text-amber-600 border-amber-200"
          onClick={() => onToast?.('缓存清理功能需在服务端手动删除 rag_storage/ 目录')}>
          🧹 清理 LLM 缓存
        </button>
      </div>
    </div>
  )
}
