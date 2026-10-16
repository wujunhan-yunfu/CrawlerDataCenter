import { useEffect, useState } from 'react'
import { App as AntApp, Button, Card, Select, Space, Table, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { AuditOut } from '../../api/types'
import { apiListAudit } from '../../api/data'
import { apiErrorMessage } from '../../api/client'
import { fmtTime } from '../../utils/format'
import PageHeader from '../../components/PageHeader'

const ACTION_LABELS: Record<string, string> = {
  'workspace.create': '创建工作空间',
  'workspace.update': '更新工作空间',
  'workspace.delete': '删除工作空间',
  'member.invite': '邀请成员',
  'member.remove': '移除成员',
  'project.create': '创建项目',
  'project.update': '更新项目',
  'project.delete': '删除项目',
}

export default function AuditLogs() {
  const { message } = AntApp.useApp()
  const [items, setItems] = useState<AuditOut[]>([])
  const [loading, setLoading] = useState(false)
  const [workspaceId, setWorkspaceId] = useState<number | undefined>()

  const load = async (wsId?: number) => {
    setLoading(true)
    try {
      setItems(await apiListAudit({ workspace_id: wsId, limit: 200 }))
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <div>
      <PageHeader
        title="审计日志"
        description="敏感操作的留痕记录"
        extra={
          <Space>
            <Select
              allowClear
              placeholder="按工作空间过滤"
              style={{ width: 180 }}
              value={workspaceId}
              onChange={(v) => {
                setWorkspaceId(v)
                void load(v)
              }}
              options={Array.from(new Set(items.map((i) => i.workspace_id))).map((id) => ({
                value: id,
                label: `工作空间 #${id}`,
              }))}
            />
            <Button icon={<ReloadOutlined />} onClick={() => void load(workspaceId)}>
              刷新
            </Button>
          </Space>
        }
      />

      <Card>
        <Table<AuditOut>
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          scroll={{ x: 900 }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '操作', dataIndex: 'action', width: 200, render: (a: string) => ACTION_LABELS[a] ?? a },
            { title: '操作人', dataIndex: 'actor_id', width: 90, render: (v: number | null) => v ?? '-' },
            {
              title: '对象',
              key: 'target',
              width: 160,
              render: (_, r) => (r.target_type ? `${r.target_type}#${r.target_id}` : '-'),
            },
            { title: '工作空间', dataIndex: 'workspace_id', width: 100, render: (v: number | null) => v ?? '-' },
            { title: 'IP', dataIndex: 'ip', width: 130, render: (v: string | null) => v ?? '-' },
            { title: '时间', dataIndex: 'created_at', width: 170, render: fmtTime },
            {
              title: '详情',
              dataIndex: 'detail_json',
              ellipsis: true,
              render: (v: Record<string, unknown> | null) =>
                v ? <Typography.Text code>{JSON.stringify(v)}</Typography.Text> : '-',
            },
          ]}
        />
      </Card>
    </div>
  )
}