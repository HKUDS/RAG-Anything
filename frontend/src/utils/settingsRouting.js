import { getDeniedRouteRecovery } from './permissionUiPolicy.js'

// Stable final fallback retained for legacy callers.
export const deniedRouteRecovery = '/preferences'

export { getDeniedRouteRecovery }

export function resolveDeniedRoute(hasPermission, currentPath = '') {
  return getDeniedRouteRecovery(hasPermission, currentPath) || deniedRouteRecovery
}

export function settingsRedirectDestination(hasSettingsRead) {
  return hasSettingsRead ? '/admin/platform' : deniedRouteRecovery
}
