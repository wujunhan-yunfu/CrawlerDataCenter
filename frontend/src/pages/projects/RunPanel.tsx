import { useEffect, useState } from 'react'
import {
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { RunOut, RunProcessOut } from '../../api/types'
import {
  apiGetRunProcess,
  apiListRuns,
  apiStopRunProcess,
  apiTriggerRun,
} from '../../api/runs'
import { apiErrorMessage } from '../../api/client'
import { fmtDuration, fmtTime } from '../../utils/format'
import { RUN_STATUS_COLORS, TRIGGER_LABELS, MODE_LABELS } from '../../api/types'
import PermissionGate from '../../components/PermissionGate'
import { usePermissionStore } from '../../stores/permissionStore'

interface Props {
  projectId: number
  workspaceId: number
}

interface TriggerForm {
  cron: string
  headless: boolean
}

export default function RunPanel({ projectId, workspaceId }: Props) {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const [runs, setRuns] = useState<RunOut[]>([])
  const [loading, setLoading] = useState(false)
  const [process, setProcess] = useState<RunProcessOut | null>(null)
  const [triggerType, setTriggerType] = useState<'once' | 'cron' | null>(null)
  const [form] = Form.useForm<TriggerForm>()
  const loadPermissions = usePermissionStore((s) => s.load)

  useEffect(() => {
    void loadPermissions({ workspaceId })
  }, [workspaceId])

  const load = async () => {
    setLoading(true)
    try {
      const [r, p] = await Promise.all([apiListRuns(projectId), apiGetRunProcess(projectId)])
      setRuns(r)
      setProcess(p)
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [projectId])

  const trigger = async (values: TriggerForm) => {
    if (!triggerType) return
    try {
      await apiTriggerRun(projectId, {
        trigger: triggerType,
        cron: triggerType === 'cron' ? values.cron : null,
        headless: values.headless,
      })
      message.success('已触发运行')
      setTriggerType(null)
      form.resetFields()
      void load()
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  const stopProcess = async () => {
    try {
      await apiStopRunProcess(projectId)
      message.success('已停止定时进程')
      void load()
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  return (
    <div>
      <PermissionGate ctx={{ workspaceId }} permission="run:trigger">
        <Space style={{ marginBottom: 16 }}>
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => setTriggerType('once')}>
            触发一次运行
          </Button>
          <Button icon={<PlayCircleOutlined />} onClick={() => setTriggerType('cron')}>
            配置定时运行
          </Button>
          <Button danger disabled={!process} onClick={() => void stopProcess()}>
            停止定时进程
          </Button>
        </Space>
      </PermissionGate>

      {process && (
        <Card size="small" title="定时进程状态" style={{ marginBottom: 16 }}>
          <Descriptions column={{ xs: 1, sm: 2, md: 3 }} size="small">
            <Descriptions.Item label="进程 ID">
              <Typography.Text code>{process.process_id}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={RUN_STATUS_COLORS[process.status] ?? 'default'}>{process.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Cron">{process.cron ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="Pod">{process.pod_name ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="PID">{process.pid ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="下次执行">{fmtTime(process.next_run_at)}</Descriptions.Item>
            <Descriptions.Item label="最后心跳">{fmtTime(process.last_heartbeat_at)}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      <Card title="运行记录" size="small">
        <Table<RunOut>
          rowKey="run_id"
          loading={loading}
          dataSource={runs}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: 'run_id', dataIndex: 'run_id', render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
            {
              title: '模式',
              dataIndex: 'mode',
              width: 90,
              render: (m: string) => MODE_LABELS[m] ?? m,
            },
            {
              title: '触发方式',
              dataIndex: 'trigger',
              width: 90,
              render: (t: string) => TRIGGER_LABELS[t] ?? t,
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (s: string) => <Tag color={RUN_STATUS_COLORS[s] ?? 'default'}>{s}</Tag>,
            },
            { title: '开始时间', dataIndex: 'started_at', width: 170, render: fmtTime },
            { title: '耗时', dataIndex: 'duration_ms', width: 100, render: fmtDuration },
            {
              title: '操作',
              key: 'actions',
              width: 100,
              render: (_, record) => (
                <Typography.Link onClick={() => navigate(`/runs/${record.run_id}`)}>详情</Typography.Link>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={triggerType === 'cron' ? '配置定时运行' : '触发一次运行'}
        open={triggerType !== null}
        onCancel={() => setTriggerType(null)}
        onOk={() => void form.validateFields().then(trigger)}
        okText="触发"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" initialValues={{ headless: true }}>
          {triggerType === 'cron' && (
            <Form.Item
              name="cron"
              label="Cron 表达式"
              rules={[{ required: true, message: '请输入 cron 表达式，例如 0 */5 * * *' }]}
            >
              <Input placeholder="例如 0 */5 * * *" />
            </Form.Item>
          )}
          <Form.Item name="headless" label="无头模式" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}