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
      onToast?.('设置已更新', 'success')
    } catch (e) { onToast?.(e.message, 'error') }
  }

  const testConnection = async () => {
    setTesting(true)
    try {
      await api.health()
      onToast?.('API 连接正常', 'success')
    } catch (e) {
      onToast?.(`连接失败: ${e.message}`, 'error')
    }
    setTesting(false)
  }

  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="font-display text-xl font-bold text-slate-100">系统设置</h2>

      {/* Parser */}
      <div className="glass p-5 space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-300"><Cpu size={16}/>解析器</h3>
        <select className="input-field"
          value={local.parser || 'docling'}
          onChange={e => { setLocal({ ...local, parser: e.target.value }); save({ parser: e.target.value }) }}>
          <option value="docling">Docling（推荐）</option>
          <option value="mineru">MinerU</option>
          <option value="paddleocr">PaddleOCR</option>
        </select>
      </div>

      {/* Models */}
      <div className="glass p-5 space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-300"><TestTube2 size={16}/>模型配置</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-slate-500">LLM 模型</label>
            <input className="input-field text-sm mt-1" value={local.llm_model || ''} readOnly />
          </div>
          <div>
            <label className="text-xs text-slate-500">Vision 模型</label>
            <input className="input-field text-sm mt-1" value={local.vision_model || ''} readOnly />
          </div>
          <div>
            <label className="text-xs text-slate-500">Embedding 模型</label>
            <input className="input-field text-sm mt-1" value={local.embedding_model || ''} readOnly />
          </div>
          <div>
            <label className="text-xs text-slate-500">Embedding 维度</label>
            <input className="input-field text-sm mt-1" value={local.embedding_dim || ''} readOnly />
          </div>
        </div>
        <button className="btn-ghost text-sm flex items-center gap-2" onClick={testConnection} disabled={testing}>
          {testing ? '测试中…' : '测试 API 连接'}
        </button>
      </div>

      {/* Chunk + Concurrency */}
      <div className="glass p-5 space-y-4">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-300"><Sliders size={16}/>处理参数</h3>
        <div>
          <div className="flex justify-between text-sm">
            <span className="text-slate-500">切块大小</span>
            <span className="font-mono text-neon-400">{local.chunk_size || 1200} tokens</span>
          </div>
          <input type="range" min="200" max="4000" step="200"
            value={local.chunk_size || 1200}
            onChange={e => { const v = e.target.value; setLocal({ ...local, chunk_size: v }) }}
            onMouseUp={() => save({ chunk_size: parseInt(local.chunk_size) })}
            className="w-full mt-2 accent-neon-500" />
        </div>
        <div>
          <div className="flex justify-between text-sm">
            <span className="text-slate-500">LLM 并发数</span>
            <span className="font-mono text-neon-400">{local.llm_max_async || 4}</span>
          </div>
          <input type="range" min="1" max="8" step="1"
            value={local.llm_max_async || 4}
            onChange={e => { const v = e.target.value; setLocal({ ...local, llm_max_async: v }) }}
            onMouseUp={() => save({ max_async: parseInt(local.llm_max_async) })}
            className="w-full mt-2 accent-neon-500" />
        </div>
      </div>

      {/* Chunking Strategy */}
      <div className="glass p-5 space-y-4">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-300"><Scissors size={16}/>文本分块策略</h3>
        <p className="text-xs text-slate-500">选择文本切割方式，不同策略影响检索精度和处理成本</p>
        <div className="space-y-2">
          {local.chunking_strategies && Object.entries(local.chunking_strategies).map(([key, meta]) => {
            const isActive = (local.chunking_strategy || 'recursive') === key
            const costColors = {
              free: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
              medium: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
              high: 'text-red-400 bg-red-500/10 border-red-500/20',
            }
            return (
              <button key={key}
                onClick={() => {
                  setLocal({ ...local, chunking_strategy: key })
                  save({ chunking_strategy: key })
                }}
                className={`w-full text-left p-3 rounded-lg border transition-all ${
                  isActive
                    ? 'border-neon-500/40 bg-neon-500/5'
                    : 'border-slate-700/50 bg-ink-900/30 hover:border-slate-600/50'
                }`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-medium ${isActive ? 'text-neon-400' : 'text-slate-300'}`}>
                        {meta.name}
                      </span>
                      {isActive && <span className="text-[10px] px-1.5 py-0.5 rounded bg-neon-500/20 text-neon-400 font-mono">当前</span>}
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">{meta.description}</p>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border shrink-0 ${costColors[meta.cost_level] || costColors.free}`}>
                    {meta.cost}
                  </span>
                </div>
              </button>
            )
          })}
        </div>
        <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/5 border border-amber-500/10">
          <AlertCircle size={14} className="text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-300/80">
            切换分块策略后，<strong>新上传的文档</strong>将使用新策略处理。已处理的文档不受影响。如需对已有文档重新分块，请先删除后重新上传。
          </p>
        </div>
      </div>

      {/* Multimodal Toggles */}
      <div className="glass p-5 space-y-3">
        <h3 className="text-sm font-medium text-slate-300">多模态处理</h3>
        {[
          { key: 'enable_image', label: '图片分析', desc: '使用 VLM 分析文档中的图片' },
          { key: 'enable_table', label: '表格处理', desc: '提取并理解表格数据' },
          { key: 'enable_equation', label: '公式解析', desc: '数学公式 LaTeX 转换' },
        ].map(({ key, label, desc }) => (
          <div key={key} className="flex items-center justify-between py-2">
            <div>
              <p className="text-sm text-slate-300">{label}</p>
              <p className="text-xs text-slate-600">{desc}</p>
            </div>
            <button
              onClick={() => { save({ [key]: !local[key] }); setLocal({ ...local, [key]: !local[key] }) }}
              className={`relative w-10 h-5 rounded-full transition-colors ${local[key] ? 'bg-neon-500' : 'bg-slate-700'}`}
              aria-label={label}
            >
              <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
                style={{ left: local[key] ? '1.25rem' : '0.125rem' }} />
            </button>
          </div>
        ))}
      </div>

      {/* Cache */}
      <div className="glass p-5">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-300 mb-3"><Trash2 size={16}/>缓存管理</h3>
        <button className="btn-ghost text-sm text-amber-400 border border-amber-500/20 px-4 py-2 rounded-lg"
          onClick={() => onToast?.('缓存清理功能需在服务端手动删除 rag_storage/ 目录')}>
          清理 LLM 缓存
        </button>
      </div>
    </div>
  )
}
