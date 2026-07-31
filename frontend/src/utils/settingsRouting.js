export const deniedRouteRecovery = '/preferences'

export function settingsRedirectDestination(hasSettingsRead) {
  return hasSettingsRead ? '/admin/platform' : deniedRouteRecovery
}
