import { useState } from 'react'
import { Play, Clock, ChevronRight } from 'lucide-react'

export default function VideoSegmentPlayer({ segments = [], onSegmentClick }) {
  const [activeIdx, setActiveIdx] = useState(null)

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  if (!segments || segments.length === 0) {
    return <p className="text-xs text-ink-muted py-4 text-center">暂无视频片段</p>
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-ink-body flex items-center gap-1.5">
        <Play size={13} className="text-coral-400" />
        视频片段 ({segments.length})
      </p>
      <div className="space-y-1.5">
        {segments.map((seg, i) => (
          <button
            key={i}
            onClick={() => { setActiveIdx(i); onSegmentClick?.(seg, i) }}
            className={`w-full flex items-center gap-3 p-2.5 rounded-xl text-left transition-all ${
              activeIdx === i ? 'bg-sky-50 border border-coral-200' : 'bg-cloud-200 border border-cloud-200 hover:bg-cloud-100'
            }`}
          >
            {/* Thumbnail placeholder */}
            <div className="w-16 h-10 rounded-lg bg-cloud-300 flex items-center justify-center shrink-0 relative">
              <Play size={14} className="text-ink-muted" />
              {activeIdx === i && (
                <div className="absolute inset-0 rounded-lg bg-sky-500/20 flex items-center justify-center">
                  <Play size={14} className="text-sky-600" fill="currentColor" />
                </div>
              )}
            </div>

            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-ink-body truncate">
                {seg.video_name || `片段 ${i + 1}`}
              </p>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-2xs text-ink-muted flex items-center gap-1">
                  <Clock size={10} />
                  {formatTime(seg.start_ts)} - {formatTime(seg.end_ts)}
                </span>
                {seg.score !== undefined && (
                  <span className="text-2xs px-1.5 py-0.5 rounded-md bg-sky-50 text-sky-600 font-medium">
                    {(seg.score * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            </div>

            <ChevronRight size={14} className={`text-ink-muted transition-transform ${activeIdx === i ? 'rotate-90' : ''}`} />
          </button>
        ))}
      </div>

      {/* Active segment info */}
      {activeIdx !== null && segments[activeIdx] && (
        <div className="p-3 rounded-xl bg-sky-50 border border-coral-100 text-xs text-coral-700 space-y-1">
          <p><span className="font-medium">视频:</span> {segments[activeIdx].video_name}</p>
          <p><span className="font-medium">时间:</span> {formatTime(segments[activeIdx].start_ts)} → {formatTime(segments[activeIdx].end_ts)}</p>
          <p><span className="font-medium">帧:</span> {segments[activeIdx].start_frame} - {segments[activeIdx].end_frame}</p>
          <p className="text-sky-500">点击跳转到该时间点开始播放</p>
        </div>
      )}
    </div>
  )
}
