import { useEffect, useState } from 'react'
import {
  App as AntApp,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { WorkspaceOut } from '../../api/types'
import {
  apiCreateWorkspace,
  apiDeleteWorkspace,
  apiListWorkspaces,
  apiUpdateWorkspace,
} from '../../api/workspaces'
import { apiErrorMessage } from '../../api/client'
import { fmtTime } from '../../utils/format'
import PermissionGate from '../../components/PermissionGate'
import { usePermissionStore } from '../../stores/permissionStore'

export default function WorkspacesList() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const [items, setItems] = useState<WorkspaceOut[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<WorkspaceOut | null>(null)
  const [form] = Form.useForm<{ name: string }>()
  const permissionCache = usePermissionStore((s) => s.cache)
  const loadPermissions = usePermissionStore((s) => s.load)

  const load = async () => {
    setLoading(true)
    try {
      const list = await apiListWorkspaces()
      setItems(list)
      void Promise.all(list.map((w) => loadPermissions({ workspaceId: w.id })))
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (ws: WorkspaceOut) => {
    setEditing(ws)
    form.setFieldsValue({ name: ws.name })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    try {
      if (editing) {
        await apiUpdateWorkspace(editing.id, { name: values.name })
        message.success('已更新工作空间')
      } else {
        await apiCreateWorkspace(values)
        message.success('已创建工作空间')
      }
      setModalOpen(false)
      void load()
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  const remove = async (id: number) => {
    try {
      await apiDeleteWorkspace(id)
      message.success('已删除工作空间')
      void load()
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  return (
    <div>
      <Card
        title="工作空间"
        extra={
          <PermissionGate permission="workspace:create">
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              创建工作空间
            </Button>
          </PermissionGate>
        }
      >
        <Table<WorkspaceOut>
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={false}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 80 },
            { title: '名称', dataIndex: 'name' },
            {
              title: '状态',
              dataIndex: 'status',
              width: 110,
              render: (s: string) => <Tag color={s === 'active' ? 'green' : 'default'}>{s}</Tag>,
            },
            { title: '创建时间', dataIndex: 'created_at', width: 180, render: fmtTime },
            {
              title: '操作',
              key: 'actions',
              width: 240,
              render: (_, record) => {
                const canEdit = permissionCache[`ws:${record.id}`]?.includes('workspace:update')
                const canDelete = permissionCache[`ws:${record.id}`]?.includes('workspace:delete')
                return (
                  <Space>
                    <Typography.Link onClick={() => navigate(`/workspaces/${record.id}`)}>进入</Typography.Link>
                    {canEdit && (
                      <Typography.Link onClick={() => openEdit(record)}>编辑</Typography.Link>
                    )}
                    {canDelete && (
                      <Popconfirm title="确定删除该工作空间？" onConfirm={() => void remove(record.id)}>
                        <Typography.Link type="danger">删除</Typography.Link>
                      </Popconfirm>
                    )}
                  </Space>
                )
              },
            },
          ]}
        />
      </Card>

      <Modal
        title={editing ? '编辑工作空间' : '创建工作空间'}
        open={modalOpen}
        onOk={() => void submit()}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[
              { required: true, message: '请输入工作空间名称' },
              { max: 128, message: '名称最多 128 字符' },
            ]}
          >
            <Input placeholder="例如: 数据采集团队" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}