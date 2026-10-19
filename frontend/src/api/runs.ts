import client from './client'
import type { DevContainerOut, DevContainerTaskOut, LoginTriggerOut, RunDetailOut, RunOut, RunProcessOut } from './types'

export interface RunTriggerPayload {
  trigger: 'once' | 'cron'
  cron?: string | null
  headless?: boolean
  webhook_secret?: string | null
}

export function apiEnsureDevContainer(projectId: string) {
  return client.post<DevContainerTaskOut>(`/projects/${projectId}/dev-container`).then((r) => r.data)
}

export function apiGetDevContainerTask(projectId: string, taskId: string) {
  return client
    .get<DevContainerTaskOut>(`/projects/${projectId}/dev-container/tasks/${taskId}`)
    .then((r) => r.data)
}

export function apiPollDevContainer(projectId: string) {
  return client.get<DevContainerOut>(`/projects/${projectId}/dev-container`).then((r) => r.data)
}

export function apiRecycleDevContainer(projectId: string) {
  return client.delete<{ ok: boolean }>(`/projects/${projectId}/dev-container`).then((r) => r.data)
}

export function apiTriggerLogin(projectId: string) {
  return client.post<LoginTriggerOut>(`/projects/${projectId}/login`).then((r) => r.data)
}

export function apiTriggerRun(projectId: string, payload: RunTriggerPayload) {
  return client.post<RunOut>(`/projects/${projectId}/runs`, payload).then((r) => r.data)
}

export function apiListRuns(projectId: string, offset = 0, limit = 50) {
  return client.get<RunOut[]>(`/projects/${projectId}/runs`, { params: { offset, limit } }).then((r) => r.data)
}

export function apiGetRunDetail(runId: string) {
  return client.get<RunDetailOut>(`/runs/${runId}`).then((r) => r.data)
}

export function apiGetRunProcess(projectId: string) {
  return client.get<RunProcessOut | null>(`/projects/${projectId}/run-process`).then((r) => r.data)
}

export function apiStopRunProcess(projectId: string) {
  return client.delete<{ ok: boolean }>(`/projects/${projectId}/run-process`).then((r) => r.data)
}