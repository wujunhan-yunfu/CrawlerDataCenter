export interface TokenOut {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserOut {
  id: number
  username: string
  email: string
  status: string
  created_at: number
}

export interface PermissionsOut {
  permissions: string[]
  workspace_id: number | null
  project_id: number | null
}

export interface WorkspaceOut {
  id: number
  name: string
  owner_id: number
  status: string
  quota_json: Record<string, unknown> | null
  created_at: number
}

export interface MemberOut {
  user_id: number
  username: string
  role: string
  scope: string
  project_id: number | null
}

export interface ProjectOut {
  id: number
  workspace_id: number
  name: string
  description: string | null
  source_type: string
  builtin_crawler_id: string | null
  crawler_id: string
  run_config_json: Record<string, unknown> | null
  status: string
  created_at: number
}

export interface DevContainerOut {
  project_id: number
  crawler_id: string
  phase: string
  dev_url: string | null
  pod_name: string | null
  error_code: string | null
  last_active_at: number | null
  expires_at: number | null
}

export interface RunOut {
  run_id: string
  project_id: number
  crawler_id: string
  workspace_id: number
  mode: string
  trigger: string
  cron: string | null
  status: string
  started_at: number
  finished_at: number | null
  duration_ms: number | null
  error_json: Record<string, unknown> | null
}

export interface RunDetailOut extends RunOut {
  saved: Record<string, unknown>[]
  process_id: string | null
}

export interface RunProcessOut {
  process_id: string
  project_id: number
  crawler_id: string
  workspace_id: number
  cron: string | null
  pod_name: string | null
  status: string
  pid: number | null
  started_at: number
  last_heartbeat_at: number | null
  next_run_at: number | null
  last_run_json: Record<string, unknown> | null
  health_json: Record<string, unknown> | null
}

export interface LoginTriggerOut {
  run_id: string
  status: string
  live_ws_url: string
  expires_at: number
}

export interface DataItemOut {
  id: number
  run_id: string
  crawler_id: string
  project_id: number
  workspace_id: number
  save_id: string
  seq: number
  kind: string
  fmt: string
  name: string
  size: number
  content_hash: string | null
  storage_backend: string
  storage_path: string | null
  source_url: string | null
  collected_at: number | null
}

export interface AuditOut {
  id: number
  actor_id: number | null
  action: string
  target_type: string | null
  target_id: number | null
  workspace_id: number | null
  detail_json: Record<string, unknown> | null
  ip: string | null
  created_at: number
}

export interface HealthOut {
  ok: boolean
  db: boolean
  redis: boolean
  version: string
}

export interface ApiErrorBody {
  ok: boolean
  error: string
  message?: string
  retry_after_ms?: number
}

export const RUN_STATUS_COLORS: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  succeeded: 'success',
  success: 'success',
  failed: 'error',
  error: 'error',
  cancelled: 'warning',
  timeout: 'warning',
  stopped: 'warning',
  unreachable: 'error',
}

export const PHASE_COLORS: Record<string, string> = {
  pending: 'default',
  starting: 'processing',
  ready: 'success',
  running: 'processing',
  stopping: 'warning',
  stopped: 'default',
  failed: 'error',
  error: 'error',
  recycling: 'warning',
  gone: 'default',
}

export const ROLE_LABELS: Record<string, string> = {
  super_admin: '超级管理员',
  workspace_owner: '空间所有者',
  workspace_admin: '空间管理员',
  developer: '开发者',
  operator: '运维',
  viewer: '只读',
}

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  builtin: '内置爬取器',
  custom: '自定义爬虫',
}

export const TRIGGER_LABELS: Record<string, string> = {
  once: '一次性',
  cron: '定时',
  login: '登录',
}

export const MODE_LABELS: Record<string, string> = {
  run: '运行',
  login: '登录',
}