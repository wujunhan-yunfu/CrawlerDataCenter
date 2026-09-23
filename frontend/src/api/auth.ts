import client from './client'
import type { PermissionsOut, TokenOut, UserOut } from './types'

export interface RegisterPayload {
  username: string
  email: string
  password: string
}

export interface LoginPayload {
  username: string
  password: string
}

export function apiLogin(payload: LoginPayload) {
  return client.post<TokenOut>('/auth/login', payload).then((r) => r.data)
}

export function apiRegister(payload: RegisterPayload) {
  return client.post<TokenOut>('/auth/register', payload).then((r) => r.data)
}

export function apiRefresh(refreshToken: string) {
  return client.post<TokenOut>('/auth/refresh', { refresh_token: refreshToken }).then((r) => r.data)
}

export function apiLogout(refreshToken?: string | null) {
  return client.post<{ ok: boolean }>('/auth/logout', { refresh_token: refreshToken ?? null }).then((r) => r.data)
}

export function apiMe() {
  return client.get<UserOut>('/auth/me').then((r) => r.data)
}

export interface PermissionsQuery {
  workspace_id?: number
  project_id?: number
}

export function apiGetPermissions(query: PermissionsQuery = {}) {
  return client.get<PermissionsOut>('/auth/permissions', { params: query }).then((r) => r.data)
}