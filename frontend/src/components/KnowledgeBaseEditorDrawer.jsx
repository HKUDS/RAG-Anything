import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Loader2, Search, Shield, Trash2, UserPlus, Users, X } from 'lucide-react'
import SideDrawer from './SideDrawer'
import { api } from '../utils/api'
import { getKnowledgeBaseEditCapabilities, getKnowledgeBaseEditorTabs } from '../utils/knowledgeBaseEditor'

function memberList(payload) {
  if (Array.isArray(payload?.members)) return payload.members
  return []
}

function candidateList(payload) {
  if (Array.isArray(payload?.candidates)) return payload.candidates
  if (Array.isArray(payload?.users)) return payload.users
  if (Array.isArray(payload?.items)) return payload.items
  return []
}

function accessLabel(member) {
  if (member.is_owner) return '所有者'
  return member.effective_access === 'operate' ? '可维护内容' : '只读'
}

export default function KnowledgeBaseEditorDrawer({
  kb,
  isOpen,
  onRequestClose,
  onSaved,
}) {
  const labelInputRef = useRef(null)
  const memberSearchRef = useRef(null)
  const [activeTab, setActiveTab] = useState('details')
  const [label, setLabel] = useState('')
  const [metadataRevision, setMetadataRevision] = useState(null)
  const [members, setMembers] = useState([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [savingLabel, setSavingLabel] = useState(false)
  const [pendingMemberIds, setPendingMemberIds] = useState(() => new Set())
  const [query, setQuery] = useState('')
  const [candidates, setCandidates] = useState([])
  const [candidateLoading, setCandidateLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const capabilities = getKnowledgeBaseEditCapabilities(kb)
  const canRename = capabilities.rename
  const canManageMembers = capabilities.manageMembers
  const hasEditableSection = canRename || canManageMembers
  const tabs = useMemo(() => getKnowledgeBaseEditorTabs(kb), [kb])

  useEffect(() => {
    if (!isOpen || !kb) return
    setActiveTab(canRename ? 'details' : 'members')
    setLabel(kb.label || kb.name || '')
    setMetadataRevision(kb.updated_at || kb.last_updated_at || null)
    setMembers([])
    setQuery('')
    setCandidates([])
    setError('')
    setNotice('')
  }, [canRename, isOpen, kb])

  useEffect(() => {
    if (!isOpen || !kb || !canManageMembers) return
    let active = true
    setMembersLoading(true)
    api.getKBMembers(kb.name)
      .then((payload) => {
        if (!active) return
        setMembers(memberList(payload))
        setMetadataRevision(payload?.updated_at || kb.updated_at || kb.last_updated_at || null)
      })
      .catch((requestError) => {
        if (active) setError(requestError.message || '成员信息加载失败')
      })
      .finally(() => {
        if (active) setMembersLoading(false)
      })
    return () => { active = false }
  }, [canManageMembers, isOpen, kb])

  useEffect(() => {
    if (!isOpen || !kb || !canManageMembers || query.trim().length < 2) {
      setCandidates([])
      return undefined
    }
    let active = true
    const timer = window.setTimeout(() => {
      setCandidateLoading(true)
      api.searchKBMemberCandidates(kb.name, query.trim(), 1)
        .then((payload) => {
          if (active) setCandidates(candidateList(payload))
        })
        .catch((requestError) => {
          if (active) setError(requestError.message || '用户搜索失败')
        })
        .finally(() => {
          if (active) setCandidateLoading(false)
        })
    }, 220)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [canManageMembers, isOpen, kb, query])

  const setMemberPending = (userId, pending) => {
    setPendingMemberIds((current) => {
      const next = new Set(current)
      if (pending) next.add(userId)
      else next.delete(userId)
      return next
    })
  }

  const saveLabel = async () => {
    const displayName = label.trim()
    if (!displayName || savingLabel || !canRename || !kb) return
    setSavingLabel(true)
    setError('')
    setNotice('')
    try {
      const result = await api.updateKBMetadata(kb.name, {
        display_name: displayName,
        expected_updated_at: metadataRevision,
      })
      const updated = result?.knowledge_base || result?.kb || result
      setMetadataRevision(updated?.updated_at || metadataRevision)
      setNotice('显示名称已保存')
      onSaved?.(updated)
    } catch (requestError) {
      setError(requestError.message || '显示名称保存失败')
    } finally {
      setSavingLabel(false)
    }
  }

  const updateMember = async (member, accessLevel) => {
    if (!kb || member.is_owner || pendingMemberIds.has(member.id)) return
    setMemberPending(member.id, true)
    setError('')
    setNotice('')
    try {
      const result = await api.updateKBMember(kb.name, member.id, accessLevel)
      const saved = result?.member || result
      setMembers((current) => current.map((item) => item.id === member.id ? { ...item, ...saved } : item))
      setNotice(`已更新 ${member.username} 的访问权限`)
      onSaved?.()
    } catch (requestError) {
      setError(requestError.message || '成员权限保存失败')
    } finally {
      setMemberPending(member.id, false)
    }
  }

  const addMember = async (candidate) => {
    if (!kb || pendingMemberIds.has(candidate.id)) return
    setMemberPending(candidate.id, true)
    setError('')
    setNotice('')
    try {
      const result = await api.updateKBMember(kb.name, candidate.id, candidate.access_level || 'read')
      const saved = result?.member || result
      setMembers((current) => current.some((item) => item.id === saved.id) ? current : [...current, saved])
      setCandidates((current) => current.filter((item) => item.id !== candidate.id))
      setNotice(`已添加 ${candidate.username}`)
      onSaved?.()
    } catch (requestError) {
      setError(requestError.message || '添加成员失败')
    } finally {
      setMemberPending(candidate.id, false)
    }
  }

  const removeMember = async (member) => {
    if (!kb || member.is_owner || member.removable === false || pendingMemberIds.has(member.id)) return
    setMemberPending(member.id, true)
    setError('')
    setNotice('')
    try {
      await api.removeKBMember(kb.name, member.id)
      setMembers((current) => current.filter((item) => item.id !== member.id))
      setNotice(`已移除 ${member.username}`)
      onSaved?.()
    } catch (requestError) {
      setError(requestError.message || '移除成员失败')
    } finally {
      setMemberPending(member.id, false)
    }
  }

  if (!kb || !hasEditableSection) return null

  return (
    <SideDrawer
      isOpen={isOpen}
      onRequestClose={onRequestClose}
      ariaLabel={`编辑知识库 ${kb.label || kb.name}`}
      initialFocusRef={canRename ? labelInputRef : memberSearchRef}
      size="lg"
    >
      <div className="flex h-full min-h-0 flex-col bg-white dark:bg-[#0f1d2e]">
        <header className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-cloud-200 px-4 sm:px-5">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink-primary">编辑知识库</h2>
            <p className="truncate text-xs text-ink-muted">{kb.label || kb.name}</p>
          </div>
          <button
            type="button"
            onClick={onRequestClose}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-cloud-100 hover:text-ink-primary"
            aria-label="关闭知识库编辑"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <div className="shrink-0 border-b border-cloud-200 px-4 sm:px-5">
          <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="知识库编辑分区">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                aria-controls={`kb-editor-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                className={`min-h-11 shrink-0 border-b-2 px-3 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'border-sky-500 text-sky-700 dark:text-sky-300'
                    : 'border-transparent text-ink-muted hover:text-ink-body'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {error && <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{error}</p>}
          {notice && <p className="mb-4 flex items-center gap-2 rounded-lg border border-sage-200 bg-sage-50 px-3 py-2 text-sm text-sage-700" role="status"><Check size={16} aria-hidden="true" />{notice}</p>}

          {activeTab === 'details' && canRename && (
            <section id="kb-editor-details" role="tabpanel" aria-label="基本信息" className="space-y-5">
              <div>
                <label htmlFor="kb-display-name" className="mb-1.5 block text-sm font-medium text-ink-body">显示名称</label>
                <input
                  ref={labelInputRef}
                  id="kb-display-name"
                  className="input-field w-full text-sm"
                  value={label}
                  maxLength={128}
                  onChange={(event) => setLabel(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void saveLabel()
                  }}
                />
                <p className="mt-2 text-xs leading-5 text-ink-muted">仅修改列表和页面中的显示名称，不会修改知识库标识、文档或索引。</p>
              </div>
              <div>
                <span className="mb-1.5 block text-sm font-medium text-ink-body">知识库标识</span>
                <output className="block break-all rounded-lg border border-cloud-200 bg-cloud-50 px-3 py-2 font-mono text-xs text-ink-muted">{kb.name}</output>
              </div>
              <button type="button" onClick={() => void saveLabel()} disabled={savingLabel || !label.trim()} className="btn-primary min-h-11 text-sm disabled:opacity-50">
                {savingLabel && <Loader2 size={15} className="animate-spin" aria-hidden="true" />}
                {savingLabel ? '保存中…' : '保存显示名称'}
              </button>
            </section>
          )}

          {activeTab === 'members' && canManageMembers && (
            <section id="kb-editor-members" role="tabpanel" aria-label="成员与权限" className="space-y-5">
              <div>
                <label htmlFor="kb-member-search" className="mb-1.5 block text-sm font-medium text-ink-body">添加用户</label>
                <div className="relative">
                  <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
                  <input
                    ref={memberSearchRef}
                    id="kb-member-search"
                    className="input-field w-full py-2 pl-9 text-sm"
                    value={query}
                    placeholder="输入至少 2 个字符搜索用户"
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </div>
                {candidateLoading && <p className="mt-2 text-xs text-ink-muted" role="status">正在搜索用户…</p>}
                {candidates.length > 0 && (
                  <ul className="mt-2 divide-y divide-cloud-200 rounded-lg border border-cloud-200" aria-label="可添加用户">
                    {candidates.map((candidate) => (
                      <li key={candidate.id} className="flex min-h-11 items-center justify-between gap-3 px-3 py-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-ink-body">{candidate.username}</p>
                          <p className="text-xs text-ink-muted">{candidate.role_name || '未分配角色'}</p>
                        </div>
                        <button type="button" onClick={() => void addMember(candidate)} disabled={pendingMemberIds.has(candidate.id)} className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg text-sky-700 hover:bg-sky-50 disabled:opacity-50" aria-label={`添加 ${candidate.username}`} title="添加用户">
                          {pendingMemberIds.has(candidate.id) ? <Loader2 size={16} className="animate-spin" /> : <UserPlus size={16} />}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center gap-2">
                  <Users size={16} className="text-ink-muted" aria-hidden="true" />
                  <h3 className="text-sm font-semibold text-ink-body">当前成员</h3>
                </div>
                {membersLoading ? (
                  <p className="py-6 text-center text-sm text-ink-muted" role="status">正在加载成员…</p>
                ) : members.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-cloud-300 px-3 py-5 text-center text-sm text-ink-muted">暂无已授权成员</p>
                ) : (
                  <ul className="divide-y divide-cloud-200 rounded-lg border border-cloud-200">
                    {members.map((member) => {
                      const pending = pendingMemberIds.has(member.id)
                      const locked = member.is_owner || member.removable === false
                      return (
                        <li key={member.id} className="flex min-h-14 items-center gap-3 px-3 py-2">
                          <div className="min-w-0 flex-1">
                            <p className="flex min-w-0 items-center gap-1.5 truncate text-sm font-medium text-ink-body">
                              {member.is_owner && <Shield size={14} className="shrink-0 text-amber-600" aria-label="所有者" />}
                              <span className="truncate">{member.username}</span>
                            </p>
                            <p className="text-xs text-ink-muted">{member.is_owner ? '所有者' : member.role_name || '未分配角色'} · {accessLabel(member)}</p>
                          </div>
                          {locked ? (
                            <span className="shrink-0 text-xs text-ink-muted">不可移除</span>
                          ) : (
                            <>
                              <select
                                className="select-field min-h-11 max-w-28 text-xs"
                                value={member.access_level || 'read'}
                                disabled={pending}
                                aria-label={`设置 ${member.username} 的访问级别`}
                                onChange={(event) => void updateMember(member, event.target.value)}
                              >
                                <option value="read">只读</option>
                                <option value="operate">可操作</option>
                              </select>
                              <button type="button" onClick={() => void removeMember(member)} disabled={pending} className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg text-rose-600 hover:bg-rose-50 disabled:opacity-50" aria-label={`移除 ${member.username}`} title="移除成员">
                                {pending ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                              </button>
                            </>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            </section>
          )}
        </div>
      </div>
    </SideDrawer>
  )
}
