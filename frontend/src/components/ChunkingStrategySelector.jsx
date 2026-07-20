import { Scissors } from 'lucide-react'
import {
  DEFAULT_CHUNKING_STRATEGY,
  getChunkingStrategyOptions,
  getChunkingStrategyPresentation,
} from '../utils/chunkingStrategyPresentation'

export default function ChunkingStrategySelector({
  strategies,
  value,
  onChange,
  helperText = '选择本次上传的文本切分方式，会影响检索效果和处理时间。',
}) {
  const options = getChunkingStrategyOptions(strategies)
  const selectedStrategy = value || DEFAULT_CHUNKING_STRATEGY
  const selected = getChunkingStrategyPresentation(selectedStrategy)

  if (options.length === 0) {
    return <p className="text-xs text-ink-muted">正在读取可用的切块方式…</p>
  }

  return (
    <section aria-labelledby="chunking-strategy-title" className="space-y-2.5">
      <div className="flex items-center gap-2">
        <Scissors size={15} className="text-ink-muted" aria-hidden="true" />
        <h3 id="chunking-strategy-title" className="text-sm font-medium text-ink-body">切块方式</h3>
      </div>
      <p className="text-xs text-ink-muted">{helperText}</p>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="选择切块方式">
        {options.map(option => {
          const selectedOption = selectedStrategy === option.id
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selectedOption}
              onClick={() => onChange(option.id)}
              className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                selectedOption
                  ? 'border-sky-300 bg-sky-50 font-medium text-sky-700'
                  : 'border-cloud-300 text-ink-muted hover:border-cloud-400 hover:text-ink-body'
              }`}
            >
              {option.name}
            </button>
          )
        })}
      </div>
      <p className="rounded-lg border border-cloud-300/70 bg-white/70 px-3 py-2 text-xs text-ink-body" aria-live="polite">
        <span className="font-medium">{selected.name}</span>
        <span className="text-ink-muted">：{selected.description}</span>
        {selected.timing && <span className="ml-2 text-sky-700">{selected.timing}</span>}
      </p>
    </section>
  )
}
