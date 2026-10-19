import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Progress,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { LoadingOutlined, SyncOutlined } from '@ant-design/icons'
import type { DevContainerOut, DevContainerTaskOut } from '../../api/types'
import { DEV_TASK_STATUS_LABELS, DEV_TASK_TERMINAL, PHASE_COLORS, RUN_STATUS_COLORS } from '../../api/types'
import {
  apiEnsureDevContainer,
  apiGetDevContainerTask,
  apiPollDevContainer,
  apiRecycleDevContainer,
} from '../../api/runs'
import { apiErrorMessage, getAccessToken } from '../../api/client'
import { fmtTime, fmtDateTimeMs } from '../../utils/format'
import PermissionGate from '../../components/PermissionGate'
import { usePermissionStore } from '../../stores/permissionStore'

interface Props {
  projectId: string
  workspaceId: string
}

const PHASE_LABELS: Record<string, string> = {
  absent: '未创建',
  pending: '等待中',
  starting: '启动中',
  ready: '就绪',
  running: '运行中',
  stopping: '停止中',
  stopped: '已停止',
  failed: '失败',
  error: '错误',
  recycling: '回收中',
  gone: '已消失',
}

// 前端兜底超时: 后端也会判超时, 这里防止网络异常导致无限轮询
const TASK_TIMEOUT_MS = 150_000
const POLL_INTERVAL_MS = 1500

export default function DevContainerPanel({ projectId, workspaceId }: Props) {
  const { message } = AntApp.useApp()
  const [container, setContainer] = useState<DevContainerOut | null>(null)
  const [task, setTask] = useState<DevContainerTaskOut | null>(null)
  const [loading, setLoading] = useState(false)
  const loadPermissions = usePermissionStore((s) => s.load)

  useEffect(() => {
    void loadPermissions({ workspaceId })
  }, [workspaceId, loadPermissions])

  const refresh = useCallback(async () => {
    try {
      setContainer(await apiPollDevContainer(projectId))
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }, [projectId, message])

  const taskActive = !!task?.task_id && !DEV_TASK_TERMINAL.includes(task.status)

  // 新标签页无法带 Authorization 头, 通过 ?token= 传递访问令牌给 CDC 反向代理
  const devHref = container?.dev_url
    ? `${container.dev_url}${container.dev_url.includes('?') ? '&' : '?'}token=${encodeURIComponent(getAccessToken() ?? '')}`
    : undefined

  // 容器状态轮询(任务进行中时暂停, 避免与任务状态轮询重复)
  useEffect(() => {
    void refresh()
    const timer = setInterval(() => {
      if (!taskActive) void refresh()
    }, 5000)
    return () => clearInterval(timer)
  }, [projectId, taskActive, refresh])

  // 循环监听 Celery 任务状态, 直到 success / failed / timeout
  useEffect(() => {
    if (!task?.task_id || DEV_TASK_TERMINAL.includes(task.status)) return
    const taskId = task.task_id
    let cancelled = false
    let timer: number | undefined
    const startedAt = Date.now()

    const tick = async () => {
      try {
        const next = await apiGetDevContainerTask(projectId, taskId)
        if (cancelled) return
        setTask(next)
        if (DEV_TASK_TERMINAL.includes(next.status)) return
      } catch (e) {
        if (cancelled) return
        if (Date.now() - startedAt > TASK_TIMEOUT_MS) {
          setTask((prev) =>
            prev ? { ...prev, status: 'timeout', message: `轮询超时: ${apiErrorMessage(e)}` } : prev,
          )
          return
        }
      }
      timer = window.setTimeout(tick, POLL_INTERVAL_MS)
    }

    timer = window.setTimeout(tick, 800)
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [projectId, task?.task_id, task?.status])

  // 终态提示 + 成功后刷新容器详情
  useEffect(() => {
    if (!task) return
    if (task.status === 'success') {
      message.success(task.message ?? '开发容器已就绪')
      void refresh()
    } else if (task.status === 'failed') {
      message.error(task.message ?? '开发容器拉起失败')
    } else if (task.status === 'timeout') {
      message.warning(task.message ?? '开发容器拉起超时')
    }
  }, [task?.status])

  const ensure = async () => {
    setLoading(true)
    setTask(null)
    try {
      const t = await apiEnsureDevContainer(projectId)
      if (t.status === 'success') {
        message.success(t.message ?? '开发容器已就绪')
        setContainer(await apiPollDevContainer(projectId))
      } else {
        setTask(t)
        message.info(t.message ?? '任务已提交，正在拉起开发容器')
      }
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  const recycle = async () => {
    setLoading(true)
    try {
      await apiRecycleDevContainer(projectId)
      message.success('开发容器已回收')
      setContainer(null)
      setTask(null)
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <PermissionGate ctx={{ workspaceId }} permission="container:manage">
        <Space style={{ marginBottom: 16 }}>
          <Button
            type="primary"
            icon={<SyncOutlined />}
            loading={loading || taskActive}
            onClick={() => void ensure()}
          >
            拉起 / 刷新容器
          </Button>
          <Button danger loading={loading} disabled={!container} onClick={() => void recycle()}>
            回收容器
          </Button>
        </Space>
      </PermissionGate>

      {task && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space>
              {taskActive && <Spin indicator={<LoadingOutlined spin />} size="small" />}
              <Typography.Text strong>拉起任务</Typography.Text>
              <Tag color={RUN_STATUS_COLORS[task.status] ?? 'default'}>
                {DEV_TASK_STATUS_LABELS[task.status] ?? task.status}
              </Tag>
              <Typography.Text type="secondary">
                {task.mode === 'local' ? '本地 ACS' : 'K8s'}
              </Typography.Text>
            </Space>
            {taskActive && <Progress percent={task.phase === 'starting' ? 60 : 20} status="active" />}
            <Descriptions column={{ xs: 1, sm: 2 }} size="small">
              <Descriptions.Item label="任务 ID">
                <Typography.Text code>{task.task_id ?? '-'}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="阶段">
                <Tag color={PHASE_COLORS[task.phase] ?? 'default'}>
                  {PHASE_LABELS[task.phase] ?? task.phase}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="耗时">
                {task.elapsed_ms != null ? `${(task.elapsed_ms / 1000).toFixed(1)}s` : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="错误码">{task.error_code ?? '-'}</Descriptions.Item>
            </Descriptions>
            {task.message && (
              <Alert
                type={
                  task.status === 'failed'
                    ? 'error'
                    : task.status === 'timeout'
                      ? 'warning'
                      : task.status === 'success'
                        ? 'success'
                        : 'info'
                }
                showIcon
                message={task.message}
              />
            )}
          </Space>
        </Card>
      )}

      {container ? (
        <Card size="small">
          <Descriptions column={{ xs: 1, sm: 2 }} size="small" bordered>
            <Descriptions.Item label="阶段">
              <Tag color={PHASE_COLORS[container.phase] ?? 'default'}>
                {PHASE_LABELS[container.phase] ?? container.phase}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="crawler_id">
              <Typography.Text code>{container.crawler_id}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="Pod 名称">{container.pod_name ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="错误码">{container.error_code ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="最近活跃">{fmtTime(container.last_active_at)}</Descriptions.Item>
            <Descriptions.Item label="过期时间">{fmtDateTimeMs(container.expires_at)}</Descriptions.Item>
            <Descriptions.Item label="访问地址" span={2}>
              {container.dev_url ? (
                <Typography.Link href={devHref} target="_blank" rel="noreferrer">
                  {container.dev_url}
                </Typography.Link>
              ) : (
                '-'
              )}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      ) : (
        <Typography.Text type="secondary">当前项目暂无开发容器，点击“拉起 / 刷新容器”创建。</Typography.Text>
      )}
    </div>
  )
}
