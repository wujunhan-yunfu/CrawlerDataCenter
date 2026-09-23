import { create } from 'zustand'
import { apiListWorkspaces } from '../api/workspaces'
import { apiHealth } from '../api/data'
import { inFlight } from '../api/dedup'
import type { HealthOut, WorkspaceOut } from '../api/types'

interface AppState {
  workspaces: WorkspaceOut[]
  health: HealthOut | null
  loadWorkspaces: () => Promise<WorkspaceOut[]>
  refreshWorkspaces: () => Promise<void>
  refreshHealth: () => Promise<HealthOut | null>
  setHealth: (h: HealthOut) => void
  setWorkspaces: (ws: WorkspaceOut[]) => void
}

const loadWorkspacesOnce = inFlight(() => apiListWorkspaces())

const fetchHealthOnce = inFlight(async () => {
  try {
    const health = await apiHealth()
    useAppStore.setState({ health })
    return health
  } catch {
    useAppStore.setState({ health: null })
    return null
  }
})

export const useAppStore = create<AppState>((set) => ({
  workspaces: [],
  health: null,

  loadWorkspaces: async () => {
    const ws = await loadWorkspacesOnce()
    set({ workspaces: ws })
    return ws
  },

  refreshWorkspaces: async () => {
    const ws = await apiListWorkspaces()
    set({ workspaces: ws })
  },

  refreshHealth: () => fetchHealthOnce(),

  setHealth: (health) => set({ health }),
  setWorkspaces: (workspaces) => set({ workspaces }),
}))