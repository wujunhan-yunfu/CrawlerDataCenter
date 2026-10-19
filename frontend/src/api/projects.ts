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

export function apiListProjects(workspaceId: string) {
  return client.get<ProjectOut[]>(`/workspaces/${workspaceId}/projects`).then((r) => r.data)
}

export function apiCreateProject(workspaceId: string, payload: ProjectCreatePayload) {
  return client.post<ProjectOut>(`/workspaces/${workspaceId}/projects`, payload).then((r) => r.data)
}

export function apiGetProject(projectId: string) {
  return client.get<ProjectOut>(`/projects/${projectId}`).then((r) => r.data)
}

export function apiUpdateProject(projectId: string, payload: ProjectUpdatePayload) {
  return client.patch<ProjectOut>(`/projects/${projectId}`, payload).then((r) => r.data)
}

export function apiDeleteProject(projectId: string) {
  return client.delete<{ ok: boolean }>(`/projects/${projectId}`).then((r) => r.data)
}