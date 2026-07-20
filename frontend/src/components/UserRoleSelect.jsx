import { useMemo } from 'react'
import { AlertTriangle, ShieldCheck } from 'lucide-react'

export const ROLE_ORDER = ['super_admin', 'dept_admin', 'teacher', 'assistant', 'student']

const ROLE_PRESENTATION = {
  super_admin: {
    label: '超级管理员',
    summary: '可管理用户、系统设置、审计记录，以及全部知识与智能体资源。',
    caution: '拥有系统最高权限，仅分配给平台运维人员。',
  },
  dept_admin: {
    label: '系部管理员',
    summary: '可管理本部门用户、知识库、智能体与教学工作流。',
    caution: '请确认其管理范围与实际职责一致。',
  },
  teacher: {
    label: '主讲教师',
    summary: '可创建和管理知识库、智能体及相关教学内容。',
  },
  assistant: {
    label: '助理教师',
    summary: '可维护知识库内容，并使用教学智能体。',
  },
  student: {
    label: '学生',
    summary: '可查看知识库并使用智能体问答。',
  },
}

export function getRolePresentation(roleName) {
  return ROLE_PRESENTATION[roleName] || {
    label: roleName || '未分配角色',
    summary: '该角色的权限说明暂不可用。',
  }
}

export function orderRoles(roles) {
  const order = new Map(ROLE_ORDER.map((name, index) => [name, index]))
  return (roles || [])
    .filter((role) => order.has(role.name))
    .sort((a, b) => order.get(a.name) - order.get(b.name))
}

export default function UserRoleSelect({ id, roles, value, onChange, disabled = false, cautionLabel }) {
  const orderedRoles = useMemo(() => orderRoles(roles), [roles])
  const selectedRole = orderedRoles.find((role) => role.id === Number(value))
  const presentation = getRolePresentation(selectedRole?.name)

  return (
    <div>
      <label className="block text-xs font-medium text-ink-body mb-1" htmlFor={id}>
        角色
        {cautionLabel && <span className="ml-2 text-2xs font-normal text-amber-600">{cautionLabel}</span>}
      </label>
      <select
        id={id}
        className="input-field user-role-select"
        value={value || ''}
        onChange={(event) => onChange(Number(event.target.value))}
        disabled={disabled}
        aria-describedby={`${id}-summary`}
      >
        {orderedRoles.map((role) => (
          <option key={role.id} value={role.id}>
            {getRolePresentation(role.name).label}
          </option>
        ))}
      </select>
      <div id={`${id}-summary`} className={`user-role-summary${presentation.caution ? ' user-role-summary--caution' : ''}`}>
        {presentation.caution ? <AlertTriangle size={15} aria-hidden="true" /> : <ShieldCheck size={15} aria-hidden="true" />}
        <div>
          <p>{presentation.summary}</p>
          {presentation.caution && <p className="user-role-summary-caution">{presentation.caution}</p>}
        </div>
      </div>
    </div>
  )
}
