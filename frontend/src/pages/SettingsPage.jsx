import { useState, useEffect } from 'react'
import { Save, Trash2, TestTube2, Cpu, Sliders, Scissors, AlertCircle } from 'lucide-react'
import { api } from '../utils/api'

export default function SettingsPage({ onToast }) {
  const [settings, setSettings] = useState({})
  const [local, setLocal] = useState({})
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    api.getSettings().then(s => { setSettings(s); setLocal(s) }).catch(err => console.error('加载设置失败:', err))
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
      <div className="card p-5 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><Cpu size={16}/>解析器</h3>
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
      <div className="card p-5 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><Sliders size={16}/>实体抽取</h3>
        <div>
          <label className="text-xs text-ink-muted dark:text-cloud-500">实体类型白名单（逗号分隔，留空=默认）</label>
          <input className="input-field text-sm mt-1" type="text"
            placeholder="如：Part,Process,Material"
            value={local.entity_types || ''}
            onChange={e => setLocal({ ...local, entity_types: e.target.value })}
            onBlur={e => save({ entity_types: e.target.value })} />
        </div>
        <div>
          <label className="text-xs text-ink-muted dark:text-cloud-500">最小连通度（0=不过滤, 1=移除孤立实体）</label>
          <input className="input-field text-sm mt-1" type="number" min="0" max="10"
            value={local.entity_extraction_min_degree ?? 0}
            onChange={e => { const v = parseInt(e.target.value) || 0; setLocal({ ...local, entity_extraction_min_degree: v }) }}
            onBlur={e => save({ entity_extraction_min_degree: parseInt(e.target.value) || 0 })} />
        </div>
      </div>

      {/* Models */}
      <div className="card p-5 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><TestTube2 size={16}/>模型配置</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-ink-muted dark:text-cloud-500">LLM 模型</label>
            <input className="input-field text-sm mt-1"
              value={local.llm_model || ''}
              onChange={e => setLocal({ ...local, llm_model: e.target.value })}
              onBlur={e => { if (e.target.value) save({ llm_model: e.target.value }) }}
              placeholder="如：qwen-plus" />
          </div>
          <div>
            <label className="text-xs text-ink-muted dark:text-cloud-500">Vision 模型</label>
            <input className="input-field text-sm mt-1" value={local.vision_model || ''} readOnly />
          </div>
          <div>
            <label className="text-xs text-ink-muted dark:text-cloud-500">Embedding 模型</label>
            <input className="input-field text-sm mt-1" value={local.embedding_model || ''} readOnly />
          </div>
          <div>
            <label className="text-xs text-ink-muted dark:text-cloud-500">Embedding 维度</label>
            <input className="input-field text-sm mt-1" value={local.embedding_dim || ''} readOnly />
          </div>
        </div>
        <button className="btn-secondary text-sm flex items-center gap-2" onClick={testConnection} disabled={testing}>
          {testing ? '测试中…' : '🔌 测试 API 连接'}
        </button>
      </div>

      {/* Chunk + Concurrency */}
      <div className="card p-5 space-y-4 dark:bg-sky-900/20 dark:border-sky-800/30">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><Sliders size={16}/>处理参数</h3>
        <div>
          <div className="flex justify-between text-sm">
            <span className="text-ink-muted dark:text-cloud-500">切块大小</span>
            <span className="font-mono text-sky-500 dark:text-sky-400 font-medium">{local.chunk_size || 800} tokens</span>
          </div>
          <input type="range" min="200" max="4000" step="200"
            value={local.chunk_size || 800}
            onChange={e => { const v = parseInt(e.target.value); setLocal({ ...local, chunk_size: v }) }}
            onMouseUp={() => save({ chunk_size: parseInt(local.chunk_size) })}
            onTouchEnd={() => save({ chunk_size: parseInt(local.chunk_size) })}
            className="w-full mt-2 accent-sky-500" />
        </div>
        <div>
          <div className="flex justify-between text-sm">
            <span className="text-ink-muted dark:text-cloud-500">最大并发数</span>
            <span className="font-mono text-sky-500 dark:text-sky-400 font-medium">{local.max_async || 4}</span>
          </div>
          <input type="range" min="1" max="16" step="1"
            value={local.max_async || 4}
            onChange={e => { const v = parseInt(e.target.value); setLocal({ ...local, max_async: v }) }}
            onMouseUp={() => save({ max_async: parseInt(local.max_async) })}
            onTouchEnd={() => save({ max_async: parseInt(local.max_async) })}
            className="w-full mt-2 accent-sky-500" />
        </div>
      </div>

      {/* Multimodal Processing Toggles */}
      <div className="card p-5 space-y-3 dark:bg-sky-900/20 dark:border-sky-800/30">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><Sliders size={16}/>多模态处理</h3>
        <p className="text-xs text-ink-muted dark:text-cloud-500">控制文档上传时是否处理各类多模态内容。关闭可加快处理速度。</p>
        {[
          { key: 'enable_image', label: '图片处理', desc: '提取图片并生成 VLM 文字描述' },
          { key: 'enable_table', label: '表格处理', desc: '提取表格并转换为结构化数据' },
          { key: 'enable_equation', label: '公式处理', desc: '提取数学公式并转换为 LaTeX' },
          { key: 'enable_video', label: '视频处理', desc: '提取视频帧并分析（需 ffmpeg）' },
        ].map(({ key, label, desc }) => (
          <div key={key} className="flex items-center justify-between py-1.5">
            <div>
              <span className="text-sm text-ink-body dark:text-cloud-300">{label}</span>
              <p className="text-xs text-ink-muted dark:text-cloud-500">{desc}</p>
            </div>
            <button
              onClick={() => {
                const newVal = !(local[key] ?? true)
                setLocal({ ...local, [key]: newVal })
                save({ [key]: newVal })
              }}
              className={`relative w-10 h-5 rounded-full transition-colors ${
                (local[key] ?? true) ? 'bg-sky-500' : 'bg-cloud-300 dark:bg-sky-800/50'
              }`}
              aria-label={`${label}: ${(local[key] ?? true) ? '已开启' : '已关闭'}`}
              role="switch"
              aria-checked={local[key] ?? true}
            >
              <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                (local[key] ?? true) ? 'translate-x-5' : 'translate-x-0.5'
              }`} />
            </button>
          </div>
        ))}
      </div>

      {/* Chunking Strategy */}
      <div className="card p-5 space-y-4 dark:bg-sky-900/20 dark:border-sky-800/30">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300"><Scissors size={16}/>文本分块策略</h3>
        <p className="text-xs text-ink-muted dark:text-cloud-500">选择文本切割方式，不同策略影响检索精度和处理成本</p>
        <div className="space-y-2">
          {local.chunking_strategies && Object.entries(local.chunking_strategies).map(([key, meta]) => {
            const isActive = (local.chunking_strategy || 'recursive') === key
            const costColors = {
              free: 'text-sage-600 bg-sage-50 border-sage-200 dark:text-sage-400 dark:bg-sage-900/20 dark:border-sage-800/30',
              medium: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-900/20 dark:border-amber-800/30',
              high: 'text-rose-600 bg-rose-50 border-rose-200 dark:text-rose-400 dark:bg-rose-900/20 dark:border-rose-800/30',
            }
            return (
              <button key={key}
                onClick={() => {
                  setLocal({ ...local, chunking_strategy: key })
                  save({ chunking_strategy: key })
                }}
                className={`w-full text-left p-3 rounded-xl border transition-all ${
                  isActive
                    ? 'border-sky-300 dark:border-sky-700 bg-sky-50/50 dark:bg-sky-900/40 shadow-cloud-sm'
                    : 'border-cloud-300 dark:border-sky-800/30 bg-cloud-50 dark:bg-sky-900/20 hover:border-cloud-400 dark:hover:border-sky-700'
                }`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-medium ${isActive ? 'text-sky-600 dark:text-sky-400' : 'text-ink-body dark:text-cloud-300'}`}>
                        {meta.name}
                      </span>
                      {isActive && <span className="text-[10px] px-1.5 py-0.5 rounded-lg bg-sky-100 dark:bg-sky-900/40 text-sky-600 dark:text-sky-400 font-mono">当前</span>}
                    </div>
                    <p className="text-xs text-ink-muted dark:text-cloud-500 mt-0.5">{meta.description}</p>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border shrink-0 ${costColors[meta.cost_level] || costColors.free}`}>
                    {meta.cost}
                  </span>
                </div>
              </button>
            )
          })}
        </div>
        <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/30">
          <AlertCircle size={14} className="text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700 dark:text-amber-300">
            切换分块策略后，<strong>新上传的文档</strong>将使用新策略处理。已处理的文档不受影响。如需对已有文档重新分块，请先删除后重新上传。
          </p>
        </div>
      </div>

      {/* Cache */}
      <div className="card p-5 dark:bg-sky-900/20 dark:border-sky-800/30">
        <h3 className="flex items-center gap-2 text-sm font-medium text-ink-body dark:text-cloud-300 mb-3"><Trash2 size={16}/>缓存管理</h3>
        <button className="btn-secondary text-sm text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-800/30"
          onClick={() => onToast?.('缓存清理功能需在服务端手动删除 rag_storage/ 目录')}>
          🧹 清理 LLM 缓存
        </button>
      </div>
    </div>
  )
}
