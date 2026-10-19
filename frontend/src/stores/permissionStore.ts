import { create } from 'zustand'
import { apiGetPermissions } from '../api/auth'

export interface PermissionCtx {
  workspaceId?: string
  projectId?: string
}

export function ctxKey(ctx: PermissionCtx = {}): string {
  if (ctx.projectId) return `project:${ctx.projectId}`
  if (ctx.workspaceId) return `ws:${ctx.workspaceId}`
  return 'global'
}

const PERMISSIONS_KEY = 'cdc_permissions'
const USER_KEY = 'cdc_user'

interface PersistedPermissions {
  userId: string | null
  cache: Record<string, string[]>
}

/** 读取当前登录用户 id, 用于把权限缓存与账号绑定, 避免切换账号后越权重用。 */
function currentUserId(): string | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { id?: unknown }
    if (typeof parsed?.id === 'string' || typeof parsed?.id === 'number') return String(parsed.id)
    return null
  } catch {
    return null
  }
}

function loadStoredCache(): Record<string, string[]> {
  try {
    const raw = localStorage.getItem(PERMISSIONS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as PersistedPermissions
    // 非当前用户或结构异常的缓存一律丢弃
    if (!parsed || parsed.userId !== currentUserId()) {
      localStorage.removeItem(PERMISSIONS_KEY)
      return {}
    }
    if (!parsed.cache || typeof parsed.cache !== 'object') return {}
    return parsed.cache
  } catch {
    localStorage.removeItem(PERMISSIONS_KEY)
    return {}
  }
}

function persistCache(cache: Record<string, string[]>): void {
  try {
    if (Object.keys(cache).length === 0) {
      localStorage.removeItem(PERMISSIONS_KEY)
      return
    }
    const payload: PersistedPermissions = { userId: currentUserId(), cache }
    localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(payload))
  } catch {
    // 忽略持久化失败(隐私模式 / 配额超限等), 不影响内存缓存
  }
}

interface PermissionState {
  cache: Record<string, string[]>
  pending: Record<string, Promise<string[]>>
  load: (ctx?: PermissionCtx) => Promise<string[]>
  reset: () => void
}

export const usePermissionStore = create<PermissionState>((set, get) => ({
  cache: loadStoredCache(),
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
        const cache = { ...get().cache, [key]: data.permissions }
        persistCache(cache)
        set({ cache })
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

  reset: () => {
    try {
      localStorage.removeItem(PERMISSIONS_KEY)
    } catch {
      // 忽略: 存储不可用时只需清空内存缓存
    }
    set({ cache: {}, pending: {} })
  },
}))
