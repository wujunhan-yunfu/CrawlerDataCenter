import { useEffect, useRef, useState } from 'react'
import { App as AntApp, Alert, Button, Card, Space, Tag, Typography } from 'antd'
import { VideoCameraOutlined } from '@ant-design/icons'
import type { LoginTriggerOut } from '../../api/types'
import { apiTriggerLogin } from '../../api/runs'
import { apiErrorMessage } from '../../api/client'
import { fmtDateTimeMs } from '../../utils/format'
import PermissionGate from '../../components/PermissionGate'
import { usePermissionStore } from '../../stores/permissionStore'

interface Props {
  projectId: string
  workspaceId: string
}

interface Frame {
  id: number
  text: string
}

interface ProxyTarget {
  pod?: string
  path?: string
  port?: number
  namespace?: string
  url?: string
}

export default function LoginPanel({ projectId, workspaceId }: Props) {
  const { message } = AntApp.useApp()
  const [trigger, setTrigger] = useState<LoginTriggerOut | null>(null)
  const [frames, setFrames] = useState<Frame[]>([])
  const [wsState, setWsState] = useState<'idle' | 'connecting' | 'open' | 'closed'>('idle')
  const [target, setTarget] = useState<ProxyTarget | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const frameId = useRef(0)
  const loadPermissions = usePermissionStore((s) => s.load)

  useEffect(() => {
    void loadPermissions({ workspaceId })
  }, [workspaceId])

  const appendFrame = (text: string) => {
    frameId.current += 1
    setFrames((prev) => [...prev.slice(-199), { id: frameId.current, text }])
  }

  const connect = (url: string) => {
    setFrames([])
    setWsState('connecting')
    setError(null)
    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch {
      setWsState('closed')
      setError('WebSocket URL 非法')
      return
    }
    wsRef.current = ws
    ws.onopen = () => setWsState('open')
    ws.onclose = () => setWsState('closed')
    ws.onerror = () => {
      setWsState('closed')
      setError('WebSocket 连接异常')
    }
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data as string)
        if (data?.type === 'proxy') {
          setTarget(data.target as ProxyTarget)
          appendFrame(`[proxy] 已获取代理目标: ${JSON.stringify(data.target)}`)
          // 若代理提供直接流地址则桥接(本地 fake 场景)
          const target = data.target as ProxyTarget
          if (target?.url && target.url.startsWith('ws')) {
            connect(target.url)
          }
          return
        }
        appendFrame(typeof ev.data === 'string' ? ev.data : JSON.stringify(ev.data))
      } catch {
        appendFrame(String(ev.data))
      }
    }
  }

  useEffect(() => {
    return () => {
      wsRef.current?.close()
    }
  }, [])

  const triggerLogin = async () => {
    setTriggering(true)
    setError(null)
    try {
      const t = await apiTriggerLogin(projectId)
      setTrigger(t)
      message.success('login 运行已触发')
      if (t.live_ws_url) connect(t.live_ws_url)
    } catch (e) {
      setError(apiErrorMessage(e))
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div>
      <PermissionGate ctx={{ workspaceId }} permission="run:trigger">
        <Space style={{ marginBottom: 16 }}>
          <Button type="primary" icon={<VideoCameraOutlined />} loading={triggering} onClick={() => void triggerLogin()}>
            触发 login 实时画面
          </Button>
          <Button
            onClick={() => {
              wsRef.current?.close()
              setFrames([])
              setWsState('idle')
            }}
          >
            断开 / 清屏
          </Button>
        </Space>
      </PermissionGate>

      {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}

      {trigger && (
        <Card size="small" title="login 运行" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Tag>run_id: {trigger.run_id}</Tag>
            <Tag color="blue">状态: {trigger.status}</Tag>
            <Tag color="purple">令牌有效期至 {fmtDateTimeMs(trigger.expires_at)}</Tag>
          </Space>
        </Card>
      )}

      {target && (
        <Alert
          type="info"
          showIcon
          message="代理目标"
          description={<Typography.Text code>{JSON.stringify(target)}</Typography.Text>}
          style={{ marginBottom: 16 }}
        />
      )}

      <Card
        size="small"
        title={
          <Space>
            <span>实时画面流</span>
            <Tag color={wsState === 'open' ? 'green' : wsState === 'connecting' ? 'processing' : 'default'}>
              {wsState === 'open' ? '已连接' : wsState === 'connecting' ? '连接中' : wsState === 'closed' ? '已断开' : '未连接'}
            </Tag>
          </Space>
        }
      >
        {frames.length === 0 ? (
          <Typography.Text type="secondary">暂无画面帧，点击“触发 login 实时画面”开始。</Typography.Text>
        ) : (
          <div
            style={{
              background: '#111',
              color: '#0f0',
              fontFamily: 'monospace',
              fontSize: 12,
              height: 420,
              overflowY: 'auto',
              padding: 12,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {frames.map((f) => (
              <div key={f.id} style={{ borderBottom: '1px dashed #333', padding: '2px 0' }}>
                {f.text}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}