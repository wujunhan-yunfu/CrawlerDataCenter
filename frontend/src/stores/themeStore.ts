import { create } from 'zustand'

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const THEME_KEY = 'cdc_theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

function loadMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw
  } catch {
    // 存储不可用时回退到跟随系统
  }
  return 'system'
}

function systemPrefersDark(): boolean {
  try {
    return window.matchMedia(DARK_QUERY).matches
  } catch {
    return false
  }
}

export function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return mode
}

/** 把解析后的主题写到 <html>, 供 CSS 变量与原生控件(color-scheme)使用。 */
function applyDomTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
}

const initialMode = loadMode()
const initialResolved = resolveTheme(initialMode)
if (typeof document !== 'undefined') applyDomTheme(initialResolved)

interface ThemeState {
  mode: ThemeMode
  resolved: ResolvedTheme
  setMode: (mode: ThemeMode) => void
}

export const useThemeStore = create<ThemeState>((set) => ({
  mode: initialMode,
  resolved: initialResolved,

  setMode: (mode) => {
    try {
      localStorage.setItem(THEME_KEY, mode)
    } catch {
      // 忽略持久化失败
    }
    const resolved = resolveTheme(mode)
    applyDomTheme(resolved)
    set({ mode, resolved })
  },
}))

// 仅当处于“跟随系统”时, 响应系统主题变化
if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  const mql = window.matchMedia(DARK_QUERY)
  const onChange = () => {
    if (useThemeStore.getState().mode !== 'system') return
    const resolved = resolveTheme('system')
    applyDomTheme(resolved)
    useThemeStore.setState({ resolved })
  }
  if (typeof mql.addEventListener === 'function') {
    mql.addEventListener('change', onChange)
  } else if (typeof mql.addListener === 'function') {
    // 兼容旧版 Safari
    mql.addListener(onChange)
  }
}
