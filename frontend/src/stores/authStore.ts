import { create } from 'zustand'
import { apiLogin, apiLogout, apiMe, apiRegister, type LoginPayload, type RegisterPayload } from '../api/auth'
import { clearTokens, setTokens } from '../api/client'
import type { UserOut } from '../api/types'
import { usePermissionStore } from './permissionStore'

const USER_KEY = 'cdc_user'

function loadStoredUser(): UserOut | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    return JSON.parse(raw) as UserOut
  } catch {
    localStorage.removeItem(USER_KEY)
    return null
  }
}

function persistUser(user: UserOut | null): void {
  if (user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } else {
    localStorage.removeItem(USER_KEY)
  }
}

interface AuthState {
  user: UserOut | null
  loading: boolean
  bootstrapped: boolean
  bootstrap: () => Promise<void>
  login: (payload: LoginPayload) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => Promise<void>
  setUser: (user: UserOut | null) => void
}

let bootstrapInFlight: Promise<void> | null = null

export const useAuthStore = create<AuthState>((set, get) => ({
  user: loadStoredUser(),
  loading: false,
  bootstrapped: false,

  setUser: (user) => {
    persistUser(user)
    set({ user })
  },

  bootstrap: async () => {
    if (get().bootstrapped) return
    // 共享进行中的校验请求, 避免 StrictMode 双触发重复调用 /auth/me
    if (!bootstrapInFlight) {
      bootstrapInFlight = (async () => {
        set({ loading: true })
        try {
          if (!localStorage.getItem('cdc_access_token')) {
            persistUser(null)
            set({ user: null })
            return
          }
          const user = await apiMe()
          persistUser(user)
          set({ user })
        } catch {
          clearTokens()
          persistUser(null)
          set({ user: null })
        } finally {
          set({ loading: false, bootstrapped: true })
        }
      })()
    }
    return bootstrapInFlight
  },

  login: async (payload) => {
    const tokens = await apiLogin(payload)
    setTokens(tokens)
    const user = await apiMe()
    persistUser(user)
    set({ user, bootstrapped: true })
  },

  register: async (payload) => {
    const tokens = await apiRegister(payload)
    setTokens(tokens)
    const user = await apiMe()
    persistUser(user)
    set({ user, bootstrapped: true })
  },

  logout: async () => {
    const refreshToken = localStorage.getItem('cdc_refresh_token')
    try {
      await apiLogout(refreshToken)
    } catch {
      // ignore
    }
    clearTokens()
    persistUser(null)
    usePermissionStore.getState().reset()
    set({ user: null })
  },
}))