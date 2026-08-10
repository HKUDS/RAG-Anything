import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Clock, Play } from 'lucide-react'
import { useControlledMediaSource } from './ControlledMedia'

function toSeconds(value) {
  return Number(value || 0) / 1000
}

function formatTime(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0))
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`
}

export default function VideoSegmentPlayer({ segments = [] }) {
  const [activeIdx, setActiveIdx] = useState(null)
  const [playbackError, setPlaybackError] = useState('')
  const videoRef = useRef(null)
  const active = activeIdx === null ? null : segments[activeIdx]
  const source = useControlledMediaSource(active)

  useEffect(() => setPlaybackError(''), [activeIdx, source])

  const seekToSegment = () => {
    if (!videoRef.current || !active) return
    videoRef.current.currentTime = toSeconds(active.start_ms)
    videoRef.current.play().catch(() => {})
  }

  if (!segments.length) {
    return <p className="text-xs text-ink-muted py-4 text-center">暂无视频片段</p>
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-ink-body flex items-center gap-1.5">
        <Play size={13} className="text-coral-400" />视频片段 ({segments.length})
      </p>
      {active && source && (
        <video ref={videoRef} className="w-full aspect-video bg-black rounded border border-cloud-200" controls preload="metadata" src={source} onLoadedMetadata={seekToSegment} onError={() => setPlaybackError('视频无法播放，请确认仍有该知识库的访问权限。')} />
      )}
      {active && !source && !playbackError && <p className="text-xs text-ink-muted">正在加载受控视频…</p>}
      {playbackError && <p className="text-xs text-red-600 flex items-center gap-1" role="alert"><AlertTriangle size={13} />{playbackError}</p>}
      <div className="space-y-1.5">
        {segments.map((seg, index) => (
          <button key={seg.segment_id || index} type="button" onClick={() => setActiveIdx(index)} className={`w-full flex items-center gap-3 p-2.5 rounded text-left transition-colors ${activeIdx === index ? 'bg-sky-50 border border-coral-200' : 'bg-cloud-200 border border-cloud-200 hover:bg-cloud-100'}`}>
            <span className="w-16 h-10 rounded bg-cloud-300 flex items-center justify-center shrink-0"><Play size={14} className="text-ink-muted" /></span>
            <span className="flex-1 min-w-0">
              <span className="block text-xs font-medium text-ink-body truncate">{seg.document_name || seg.video_name || `片段 ${index + 1}`}</span>
              <span className="flex items-center gap-1 mt-0.5 text-2xs text-ink-muted"><Clock size={10} />{formatTime(toSeconds(seg.start_ms ?? seg.start_ts))} - {formatTime(toSeconds(seg.end_ms ?? seg.end_ts))}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
