import client from './client'
import type { DevContainerOut, LoginTriggerOut, RunDetailOut, RunOut, RunProcessOut } from './types'

export interface RunTriggerPayload {
  trigger: 'once' | 'cron'
  cron?: string | null
  headless?: boolean
  webhook_secret?: string | null
}

export function apiEnsureDevContainer(projectId: number) {
  return client.post<DevContainerOut>(`/projects/${projectId}/dev-container`).then((r) => r.data)
}

export function apiPollDevContainer(projectId: number) {
  return client.get<DevContainerOut>(`/projects/${projectId}/dev-container`).then((r) => r.data)
}

export function apiRecycleDevContainer(projectId: number) {
  return client.delete<{ ok: boolean }>(`/projects/${projectId}/dev-container`).then((r) => r.data)
}

export function apiTriggerLogin(projectId: number) {
  return client.post<LoginTriggerOut>(`/projects/${projectId}/login`).then((r) => r.data)
}

export function apiTriggerRun(projectId: number, payload: RunTriggerPayload) {
  return client.post<RunOut>(`/projects/${projectId}/runs`, payload).then((r) => r.data)
}

export function apiListRuns(projectId: number, offset = 0, limit = 50) {
  return client.get<RunOut[]>(`/projects/${projectId}/runs`, { params: { offset, limit } }).then((r) => r.data)
}

export function apiGetRunDetail(runId: string) {
  return client.get<RunDetailOut>(`/runs/${runId}`).then((r) => r.data)
}

export function apiGetRunProcess(projectId: number) {
  return client.get<RunProcessOut | null>(`/projects/${projectId}/run-process`).then((r) => r.data)
}

export function apiStopRunProcess(projectId: number) {
  return client.delete<{ ok: boolean }>(`/projects/${projectId}/run-process`).then((r) => r.data)
}