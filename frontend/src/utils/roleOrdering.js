/**
 * 角色等级与可分配性纯逻辑（无 React 依赖，便于 node:test 直接测试）。
 * 等级顺序与后端 permissions.py 一致：super_admin > dept_admin > teacher > assistant > student。
 */
export const ROLE_ORDER = ['super_admin', 'dept_admin', 'teacher', 'assistant', 'student']

export const ROLE_RANK = Object.fromEntries(ROLE_ORDER.map((name, index) => [name, index]))

/**
 * 操作者是否可分配目标角色：可分配等级 ≤ 自身（未知角色一律拒绝）。
 */
export function canAssignRole(actorRole, targetRole) {
  const actorRank = ROLE_RANK[actorRole]
  const targetRank = ROLE_RANK[targetRole]
  if (actorRank === undefined || targetRank === undefined) return false
  return targetRank >= actorRank
}

export function orderRoles(roles) {
  const order = new Map(ROLE_ORDER.map((name, index) => [name, index]))
  return (roles || [])
    .filter((role) => order.has(role.name))
    .sort((a, b) => order.get(a.name) - order.get(b.name))
}

/**
 * 按操作者等级过滤可选角色；未提供 actorRole 时保持全量（向后兼容）。
 */
export function filterAssignableRoles(roles, actorRole) {
  const ordered = orderRoles(roles)
  if (!actorRole) return ordered
  return ordered.filter((role) => canAssignRole(actorRole, role.name))
}
