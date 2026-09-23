import { create } from 'zustand'
import { apiGetPermissions } from '../api/auth'

export interface PermissionCtx {
  workspaceId?: number
  projectId?: number
}

export function ctxKey(ctx: PermissionCtx = {}): string {
  if (ctx.projectId) return `project:${ctx.projectId}`
  if (ctx.workspaceId) return `ws:${ctx.workspaceId}`
  return 'global'
}

interface PermissionState {
  cache: Record<string, string[]>
  pending: Record<string, Promise<string[]>>
  load: (ctx?: PermissionCtx) => Promise<string[]>
  reset: () => void
}

export const usePermissionStore = create<PermissionState>((set, get) => ({
  cache: {},
  pending: {},

  load: (ctx = {}) => {
    const key = ctxKey(ctx)
    const cached = get().cache[key]
    if (cached) return Promise.resolve(cached)
    const inFlight = get().pending[key]
    if (inFlight) return inFlight

    const promise = apiGetPermissions({
      workspace_id: ctx.workspaceId,
      project_id: ctx.projectId,
    })
      .then((data) => {
        set((s) => ({ cache: { ...s.cache, [key]: data.permissions } }))
        return data.permissions
      })
      .catch(() => [])
      .finally(() => {
        set((s) => {
          const next = { ...s.pending }
          delete next[key]
          return { pending: next }
        })
      })
    set((s) => ({ pending: { ...s.pending, [key]: promise } }))
    return promise
  },

  reset: () => set({ cache: {}, pending: {} }),
}))