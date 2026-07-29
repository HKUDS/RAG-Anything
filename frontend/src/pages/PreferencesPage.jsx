import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Check, Image, Loader2, RotateCcw, Save } from 'lucide-react'
import { api } from '../utils/api'

export default function PreferencesPage({ onToast }) {
  const [profiles, setProfiles] = useState([])
  const [stored, setStored] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([api.listVisionModels('vlm'), api.getModelPreferences()])
      .then(([catalog, preference]) => {
        if (cancelled) return
        setProfiles(Array.isArray(catalog?.profiles) ? catalog.profiles : [])
        setStored(preference)
        setSelected(preference?.vision_vlm_profile_id ?? null)
      })
      .catch(err => !cancelled && setError(err.message || '加载个人偏好失败'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [])

  const displayedProfiles = useMemo(() => {
    const current = stored?.profile
    if (!current?.id || profiles.some(profile => profile.id === current.id)) return profiles
    return [current, ...profiles]
  }, [profiles, stored])
  const currentProfile = displayedProfiles.find(profile => profile.id === selected)
  const storedId = stored?.vision_vlm_profile_id ?? null
  const isDirty = selected !== storedId

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      const result = await api.updateModelPreferences({ vision_vlm_profile_id: selected })
      setStored(result)
      setSelected(result?.vision_vlm_profile_id ?? null)
      onToast?.('图片理解模型偏好已保存', 'success')
    } catch (err) {
      setSelected(storedId)
      setError(err.message || '保存个人偏好失败')
      onToast?.(err.message || '保存个人偏好失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="animate-spin text-sky-500" /></div>
  }

  return (
    <div className="w-full max-w-3xl space-y-5">
      <div className="page-header page-header-divider">
        <div>
          <h2 className="page-title">个人偏好</h2>
          <p className="page-subtitle">选择后续图片理解任务使用的模型。供应商连接信息仅由管理员维护。</p>
        </div>
      </div>
      {error && <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"><AlertCircle size={16} className="mt-0.5 shrink-0" />{error}</div>}
      <section className="card space-y-4 p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-sky-50 p-2 text-sky-600"><Image size={18} /></div>
          <div><h3 className="font-medium">图片理解模型</h3><p className="mt-1 text-xs text-ink-muted dark:text-cloud-500">用于 OCR、图片描述、视频帧理解和问图；只影响后续请求与新任务。</p></div>
        </div>
        <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-cloud-300 p-3 hover:border-sky-400">
          <input type="radio" name="vision-vlm" checked={selected === null} onChange={() => setSelected(null)} />
          <span><span className="block text-sm font-medium">继承平台默认</span><span className="mt-0.5 block text-xs text-ink-muted dark:text-cloud-500">平台默认变化后自动生效</span></span>
          {selected === null && <Check size={16} className="ml-auto text-sky-600" />}
        </label>
        <div className="space-y-2">
          {currentProfile?.available === false && selected && <div className="rounded-lg bg-amber-50 p-2 text-xs text-amber-700">当前保存的模型不可用：{currentProfile.unavailable_reason || 'catalog_missing'}。请选择其他模型或恢复继承。</div>}
          {displayedProfiles.map(profile => (
            <label key={profile.id} className={`flex items-center gap-3 rounded-lg border p-3 ${profile.available ? 'cursor-pointer hover:border-sky-400' : 'cursor-not-allowed opacity-60'} ${selected === profile.id ? 'border-sky-500 bg-sky-50/50' : 'border-cloud-300'}`}>
              <input type="radio" name="vision-vlm" disabled={!profile.available} checked={selected === profile.id} onChange={() => setSelected(profile.id)} />
              <span className="min-w-0"><span className="block truncate text-sm font-medium">{profile.display_name}</span><span className="mt-0.5 block text-xs text-ink-muted dark:text-cloud-500">{profile.provider} · {profile.model}</span></span>
              <span className={`ml-auto text-xs ${profile.available ? 'text-emerald-600' : 'text-amber-700'}`}>{profile.available ? '可用' : (profile.unavailable_reason || '不可用')}</span>
            </label>
          ))}
          {!displayedProfiles.length && <p className="py-3 text-sm text-ink-muted dark:text-cloud-500">暂无可用的图片理解模型。</p>}
        </div>
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <button className="btn-secondary flex items-center gap-2 text-sm" onClick={() => setSelected(storedId)} disabled={saving || !isDirty}><RotateCcw size={14} />撤销</button>
          <button className="btn-primary flex items-center gap-2 text-sm" onClick={save} disabled={saving || !isDirty}><Save size={14} />{saving ? '保存中...' : '保存偏好'}</button>
        </div>
      </section>
    </div>
  )
}
