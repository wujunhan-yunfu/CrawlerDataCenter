import client from './client'
import type { MemberOut, WorkspaceOut } from './types'

export interface WorkspaceCreatePayload {
  name: string
  quota?: Record<string, unknown> | null
}

export interface WorkspaceUpdatePayload {
  name?: string
  quota?: Record<string, unknown> | null
  status?: string
}

export interface MemberInvitePayload {
  username: string
  role: string
  project_id?: string | null
}

export function apiListWorkspaces() {
  return client.get<WorkspaceOut[]>('/workspaces').then((r) => r.data)
}

export function apiCreateWorkspace(payload: WorkspaceCreatePayload) {
  return client.post<WorkspaceOut>('/workspaces', payload).then((r) => r.data)
}

export function apiGetWorkspace(id: string) {
  return client.get<WorkspaceOut>(`/workspaces/${id}`).then((r) => r.data)
}

export function apiUpdateWorkspace(id: string, payload: WorkspaceUpdatePayload) {
  return client.patch<WorkspaceOut>(`/workspaces/${id}`, payload).then((r) => r.data)
}

export function apiDeleteWorkspace(id: string) {
  return client.delete<{ ok: boolean }>(`/workspaces/${id}`).then((r) => r.data)
}

export function apiListMembers(workspaceId: string) {
  return client.get<MemberOut[]>(`/workspaces/${workspaceId}/members`).then((r) => r.data)
}

export function apiAddMember(workspaceId: string, payload: MemberInvitePayload) {
  return client.post<MemberOut>(`/workspaces/${workspaceId}/members`, payload).then((r) => r.data)
}

export function apiRemoveMember(workspaceId: string, userId: string) {
  return client.delete<{ ok: boolean }>(`/workspaces/${workspaceId}/members/${userId}`).then((r) => r.data)
}