import { useEffect, useState } from 'react'
import {
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Space,
  Tag,
  Typography,
} from 'antd'
import { SyncOutlined } from '@ant-design/icons'
import type { DevContainerOut } from '../../api/types'
import {
  apiEnsureDevContainer,
  apiPollDevContainer,
  apiRecycleDevContainer,
} from '../../api/runs'
import { apiErrorMessage } from '../../api/client'
import { fmtTime, fmtDateTimeMs } from '../../utils/format'
import { PHASE_COLORS } from '../../api/types'
import PermissionGate from '../../components/PermissionGate'
import { usePermissionStore } from '../../stores/permissionStore'

interface Props {
  projectId: number
  workspaceId: number
}

const PHASE_LABELS: Record<string, string> = {
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

export default function DevContainerPanel({ projectId, workspaceId }: Props) {
  const { message } = AntApp.useApp()
  const [container, setContainer] = useState<DevContainerOut | null>(null)
  const [loading, setLoading] = useState(false)
  const loadPermissions = usePermissionStore((s) => s.load)

  useEffect(() => {
    void loadPermissions({ workspaceId })
  }, [workspaceId])

  const poll = async () => {
    setLoading(true)
    try {
      setContainer(await apiPollDevContainer(projectId))
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  const ensure = async () => {
    setLoading(true)
    try {
      const c = await apiEnsureDevContainer(projectId)
      setContainer(c)
      message.success('开发容器已拉起')
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
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void poll()
    const timer = setInterval(() => {
      void apiPollDevContainer(projectId).then(setContainer).catch(() => undefined)
    }, 5000)
    return () => clearInterval(timer)
  }, [projectId])

  return (
    <div>
      <PermissionGate ctx={{ workspaceId }} permission="container:manage">
        <Space style={{ marginBottom: 16 }}>
          <Button type="primary" icon={<SyncOutlined />} loading={loading} onClick={() => void ensure()}>
            拉起 / 刷新容器
          </Button>
          <Button danger loading={loading} disabled={!container} onClick={() => void recycle()}>
            回收容器
          </Button>
        </Space>
      </PermissionGate>
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
                <Typography.Link href={container.dev_url} target="_blank" rel="noreferrer">
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