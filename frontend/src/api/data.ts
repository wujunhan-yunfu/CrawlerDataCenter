import client from './client'
import type { AuditOut, DataItemOut, HealthOut } from './types'

export function apiListData(projectId: number, params: { run_id?: string; offset?: number; limit?: number } = {}) {
  return client.get<DataItemOut[]>(`/projects/${projectId}/data`, { params }).then((r) => r.data)
}

export function apiDownloadData(itemId: number) {
  return client.get<ArrayBuffer>(`/data/${itemId}/download`, { responseType: 'arraybuffer' }).then((r) => r.data)
}

export interface AuditQuery {
  workspace_id?: number
  actor_id?: number
  action?: string
  offset?: number
  limit?: number
}

export function apiListAudit(query: AuditQuery = {}) {
  return client.get<AuditOut[]>('/audit', { params: query }).then((r) => r.data)
}

export function apiHealth() {
  // /healthz 不走 /api/v1 前缀, 需以同源根路径请求(绝对 URL 会跳过 client 的 baseURL)
  return client.get<HealthOut>(`${window.location.origin}/healthz`).then((r) => r.data)
}