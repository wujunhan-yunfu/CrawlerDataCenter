import { useEffect, useState } from 'react'
import { App as AntApp, Button, Card, Input, Space, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import type { DataItemOut } from '../../api/types'
import { apiDownloadData, apiListData } from '../../api/data'
import { apiErrorMessage } from '../../api/client'
import { downloadBlob, fmtBytes, fmtTime } from '../../utils/format'
import PermissionGate from '../../components/PermissionGate'
import { usePermissionStore } from '../../stores/permissionStore'

interface Props {
  projectId: string
  workspaceId: string
}

const FMT_TAGS: Record<string, string> = {
  json: 'geekblue',
  jsonl: 'geekblue',
  csv: 'green',
  txt: 'default',
  html: 'volcano',
  img: 'purple',
}

export default function DataPanel({ projectId, workspaceId }: Props) {
  const { message } = AntApp.useApp()
  const [items, setItems] = useState<DataItemOut[]>([])
  const [loading, setLoading] = useState(false)
  const [runId, setRunId] = useState<string>('')
  const loadPermissions = usePermissionStore((s) => s.load)

  useEffect(() => {
    void loadPermissions({ workspaceId })
  }, [workspaceId])

  const load = async () => {
    setLoading(true)
    try {
      setItems(await apiListData(projectId, { run_id: runId || undefined, limit: 100 }))
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [projectId])

  const download = async (item: DataItemOut) => {
    try {
      const buf = await apiDownloadData(item.id)
      const ext = item.fmt === 'img' ? 'png' : item.fmt
      downloadBlob(buf, `${item.name || item.save_id}.${ext}`)
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  return (
    <PermissionGate ctx={{ workspaceId }} permission="data:read">
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="按 run_id 过滤（留空显示全部）"
          allowClear
          style={{ width: 320 }}
          onSearch={(v) => {
            setRunId(v)
            setTimeout(() => void load(), 0)
          }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </Space>
      <Card size="small">
        <Table<DataItemOut>
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          scroll={{ x: 1000 }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '名称', dataIndex: 'name' },
            {
              title: '类型',
              dataIndex: 'fmt',
              width: 90,
              render: (f: string) => <Tag color={FMT_TAGS[f] ?? 'default'}>{f}</Tag>,
            },
            { title: 'run_id', dataIndex: 'run_id', width: 150, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
            { title: '大小', dataIndex: 'size', width: 100, render: fmtBytes },
            {
              title: '存储',
              dataIndex: 'storage_backend',
              width: 100,
              render: (s: string) => <Tag color={s === 'mongo' ? 'gold' : 'cyan'}>{s}</Tag>,
            },
            { title: '采集时间', dataIndex: 'collected_at', width: 170, render: fmtTime },
            {
              title: '操作',
              key: 'actions',
              width: 100,
              render: (_, record) => (
                <Button size="small" icon={<DownloadOutlined />} onClick={() => void download(record)}>
                  下载
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </PermissionGate>
  )
}