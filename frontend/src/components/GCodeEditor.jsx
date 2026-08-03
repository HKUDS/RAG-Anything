import { useState, useRef, useCallback } from 'react'
import { Play, AlertTriangle, Copy, Check, Loader2 } from 'lucide-react'
import { api } from '../utils/api'

// G-code 词法模式
const PATTERNS = [
  { regex: /\b[GM]\d{2}(\.\d+)?\b/g, cls: 'text-sky-600 font-semibold' },       // G/M codes
  { regex: /\b[XYZIJKR]\s*-?[\d.]+/g, cls: 'text-amber-600' },                    // Coordinates
  { regex: /\b[SF]\s*[\d.]+/g, cls: 'text-sage-600' },                            // Speed/Feed
  { regex: /[TN]\d+/g, cls: 'text-sky-600' },                                   // Tool numbers
  { regex: /\(.*?\)|;.*/g, cls: 'text-ink-muted italic' },                         // Comments
  { regex: /\bG00\b.*Z\s*-\d/g, cls: 'bg-rose-100 text-rose-700 rounded px-0.5' }, // Risk: rapid to negative Z
]

function highlightLine(line) {
  if (!line || line.startsWith('(') || line.startsWith(';') || line.startsWith('%')) {
    return <span className="text-ink-muted italic">{line}</span>
  }
  // 基于正则的轻量高亮
  let parts = [{ text: line, cls: '' }]
  for (const { regex, cls } of PATTERNS) {
    const newParts = []
    for (const part of parts) {
      if (part.cls) { newParts.push(part); continue }
      let lastIdx = 0
      let match
      const text = part.text
      regex.lastIndex = 0
      while ((match = regex.exec(text)) !== null) {
        if (match.index > lastIdx) newParts.push({ text: text.slice(lastIdx, match.index), cls: '' })
        newParts.push({ text: match[0], cls })
        lastIdx = match.index + match[0].length
      }
      if (lastIdx < text.length) newParts.push({ text: text.slice(lastIdx), cls: '' })
    }
    parts = newParts
  }
  return parts.map((p, i) => p.cls ? <span key={i} className={p.cls}>{p.text}</span> : <span key={i}>{p.text}</span>)
}

export default function GCodeEditor({ onParseResult, canParse = false }) {
  const [code, setCode] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [lang, setLang] = useState('gcode')
  const textareaRef = useRef()
  const preRef = useRef()

  const handleParse = useCallback(async () => {
    if (!canParse || !code.trim() || loading) return
    setLoading(true)
    try {
      const res = await api.post('/autorepair/code/parse', { query: code, language: lang })
      const data = res
      setResult(data)
      onParseResult?.(data)
    } catch (e) {
      setResult({ error: '解析请求失败' })
    } finally { setLoading(false) }
  }, [canParse, code, lang, loading, onParseResult])

  const lines = code.split('\n')

  if (!canParse) return null

  return (
    <div className="space-y-3">
      {/* 工具栏 */}
      <div className="flex items-center gap-2">
        <select value={lang} onChange={e => setLang(e.target.value)}
          className="px-3 py-1.5 rounded-lg border border-cloud-300 text-sm bg-white text-ink-body">
          <option value="gcode">G 代码</option>
          <option value="plc_instruction_list">PLC 指令表</option>
        </select>
        <button onClick={handleParse} disabled={loading || !code.trim()}
          className="btn-primary px-4 py-1.5 rounded-lg text-sm flex items-center gap-1.5 disabled:opacity-50">
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          解析
        </button>
        {result && (
          <button onClick={() => { navigator.clipboard.writeText(JSON.stringify(result, null, 2)); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
            className="px-3 py-1.5 rounded-lg text-xs border border-cloud-300 text-ink-body hover:bg-cloud-200 flex items-center gap-1">
            {copied ? <Check size={13} className="text-sage-500" /> : <Copy size={13} />}
            {copied ? '已复制' : '复制结果'}
          </button>
        )}
      </div>

      {/* 编辑器 */}
      <div className="relative rounded-xl border border-cloud-300 overflow-hidden bg-cloud-200">
        <div className="flex">
          {/* 行号 */}
          <div className="shrink-0 bg-cloud-100 py-3 select-none border-r border-cloud-300">
            {lines.map((_, i) => (
              <div key={i} className="text-right px-2 text-2xs font-mono text-ink-muted leading-5 h-5">
                {i + 1}
              </div>
            ))}
            {lines.length === 0 && <div className="h-5" />}
          </div>
          {/* 带高亮叠层的代码区域 */}
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={code}
              onChange={e => setCode(e.target.value)}
              onScroll={e => { if (preRef.current) preRef.current.scrollTop = e.target.scrollTop }}
              placeholder="粘贴 G 代码或 PLC 指令表…&#10;&#10;G90 G21&#10;G00 X10 Y20 Z5&#10;G01 Z-2 F100&#10;M30"
              className="w-full h-full min-h-[200px] p-3 font-mono text-sm bg-transparent resize-none
                focus:outline-none text-transparent caret-ink-body z-10 relative"
              style={{ lineHeight: '1.25rem' }}
            />
            {/* 高亮叠层 */}
            <pre ref={preRef} className="absolute inset-0 p-3 font-mono text-sm pointer-events-none overflow-hidden"
              style={{ lineHeight: '1.25rem' }}>
              <code className="text-ink-body">
                {lines.map((l, i) => (
                  <div key={i} className="h-5 leading-5">{highlightLine(l)}</div>
                ))}
              </code>
            </pre>
          </div>
        </div>
      </div>

      {/* 解析结果 */}
      {result && (
        <div className="card p-4 space-y-3 max-h-[300px] overflow-y-auto">
          {result.error ? (
            <p className="text-sm text-rose-500">{result.error}</p>
          ) : (
            <>
              {result.summary && (
                <div className="p-3 rounded-xl bg-sage-50 border border-sage-100 text-sm text-sage-700">{result.summary}</div>
              )}
              {result.lines && (
                <div className="space-y-0.5">
                  {result.lines.map((l, i) => (
                    <div key={i} className={`flex gap-3 text-xs py-1 px-2 rounded ${l.type === 'comment_or_meta' ? 'text-ink-muted' : ''}`}>
                      <span className="text-ink-muted font-mono w-7 text-right shrink-0">{l.line_number}</span>
                      <code className="font-mono flex-1 text-ink-body">{l.code}</code>
                      {l.explanation && l.explanation !== '—' && (
                        <span className="text-ink-muted max-w-[200px] truncate hidden lg:inline">{l.explanation}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {result.risks?.length > 0 && (
                <div className="p-3 rounded-xl bg-rose-50 border border-rose-100 space-y-1">
                  <p className="text-xs font-semibold text-rose-600 flex items-center gap-1">
                    <AlertTriangle size={13} /> 风险检测 ({result.risks.length})
                  </p>
                  {result.risks.map((r, i) => (
                    <div key={i} className="text-xs text-rose-700 flex gap-2">
                      <span className="font-mono text-rose-400">L{r.line}</span>
                      <span>{r.risk}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
