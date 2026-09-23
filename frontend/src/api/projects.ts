import client from './client'
import type { ProjectOut } from './types'

export interface ProjectCreatePayload {
  name: string
  description?: string | null
  source_type: string
  builtin_crawler_id?: string | null
  run_config?: Record<string, unknown> | null
}

export interface ProjectUpdatePayload {
  name?: string
  description?: string | null
  run_config?: Record<string, unknown> | null
  status?: string
}

export function apiListProjects(workspaceId: number) {
  return client.get<ProjectOut[]>(`/workspaces/${workspaceId}/projects`).then((r) => r.data)
}

export function apiCreateProject(workspaceId: number, payload: ProjectCreatePayload) {
  return client.post<ProjectOut>(`/workspaces/${workspaceId}/projects`, payload).then((r) => r.data)
}

export function apiGetProject(projectId: number) {
  return client.get<ProjectOut>(`/projects/${projectId}`).then((r) => r.data)
}

export function apiUpdateProject(projectId: number, payload: ProjectUpdatePayload) {
  return client.patch<ProjectOut>(`/projects/${projectId}`, payload).then((r) => r.data)
}

export function apiDeleteProject(projectId: number) {
  return client.delete<{ ok: boolean }>(`/projects/${projectId}`).then((r) => r.data)
}