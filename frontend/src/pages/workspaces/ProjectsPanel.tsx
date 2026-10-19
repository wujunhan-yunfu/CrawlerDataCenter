import { useEffect, useState } from 'react'
import {
  App as AntApp,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ProjectOut } from '../../api/types'
import { apiCreateProject, apiDeleteProject, apiListProjects, apiUpdateProject } from '../../api/projects'
import { apiErrorMessage } from '../../api/client'
import { fmtTime } from '../../utils/format'
import { SOURCE_TYPE_LABELS } from '../../api/types'
import PermissionGate from '../../components/PermissionGate'
import { usePermissionStore } from '../../stores/permissionStore'

interface Props {
  workspaceId: string
}

interface ProjectForm {
  name: string
  source_type: 'builtin' | 'custom'
  description?: string
  builtin_crawler_id?: string
}

export default function ProjectsPanel({ workspaceId }: Props) {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const [items, setItems] = useState<ProjectOut[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<ProjectOut | null>(null)
  const [form] = Form.useForm<ProjectForm>()
  const permissionCache = usePermissionStore((s) => s.cache)
  const loadPermissions = usePermissionStore((s) => s.load)

  const load = async () => {
    setLoading(true)
    try {
      setItems(await apiListProjects(workspaceId))
    } catch (e) {
      message.error(apiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    void loadPermissions({ workspaceId })
  }, [workspaceId])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (p: ProjectOut) => {
    setEditing(p)
    form.setFieldsValue({
      name: p.name,
      source_type: p.source_type as 'builtin' | 'custom',
      description: p.description ?? undefined,
      builtin_crawler_id: p.builtin_crawler_id ?? undefined,
    })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    try {
      if (editing) {
        await apiUpdateProject(editing.id, {
          name: values.name,
          description: values.description ?? null,
          status: undefined,
        })
        message.success('已更新项目')
      } else {
        await apiCreateProject(workspaceId, {
          name: values.name,
          description: values.description ?? null,
          source_type: values.source_type,
          builtin_crawler_id: values.source_type === 'builtin' ? values.builtin_crawler_id : null,
        })
        message.success('已创建项目')
      }
      setModalOpen(false)
      void load()
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  const remove = async (id: string) => {
    try {
      await apiDeleteProject(id)
      message.success('已删除项目')
      void load()
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  return (
    <div>
      <Card
        extra={
          <PermissionGate ctx={{ workspaceId }} permission="project:create">
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              创建项目
            </Button>
          </PermissionGate>
        }
      >
        <Table<ProjectOut>
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={false}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '名称', dataIndex: 'name' },
            {
              title: '来源',
              dataIndex: 'source_type',
              width: 110,
              render: (s: string) => <Tag color={s === 'builtin' ? 'blue' : 'purple'}>{SOURCE_TYPE_LABELS[s] ?? s}</Tag>,
            },
            {
              title: 'crawler_id',
              dataIndex: 'crawler_id',
              render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (s: string) => <Tag color={s === 'active' ? 'green' : 'default'}>{s}</Tag>,
            },
            { title: '创建时间', dataIndex: 'created_at', width: 170, render: fmtTime },
            {
              title: '操作',
              key: 'actions',
              width: 200,
              render: (_, record) => {
                const canEdit = permissionCache[`ws:${workspaceId}`]?.includes('project:update')
                const canDelete = permissionCache[`ws:${workspaceId}`]?.includes('project:delete')
                return (
                  <Space>
                    <Typography.Link onClick={() => navigate(`/projects/${record.id}`)}>管理</Typography.Link>
                    {canEdit && (
                      <Typography.Link onClick={() => openEdit(record)}>编辑</Typography.Link>
                    )}
                    {canDelete && (
                      <Popconfirm title="确定删除该项目？" onConfirm={() => void remove(record.id)}>
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
        title={editing ? '编辑项目' : '创建项目'}
        open={modalOpen}
        onOk={() => void submit()}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" initialValues={{ source_type: 'custom' }}>
          <Form.Item
            name="name"
            label="名称"
            rules={[
              { required: true, message: '请输入项目名称' },
              { max: 128, message: '名称最多 128 字符' },
            ]}
          >
            <Input placeholder="例如: 新闻资讯采集" />
          </Form.Item>
          <Form.Item name="source_type" label="来源" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'custom', label: '自定义爬虫' },
                { value: 'builtin', label: '内置爬取器' },
              ]}
            />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) => prev.source_type !== cur.source_type}
          >
            {({ getFieldValue }) =>
              getFieldValue('source_type') === 'builtin' ? (
                <Form.Item name="builtin_crawler_id" label="内置爬取器 ID">
                  <Input placeholder="例如: builtin-news" />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={512} placeholder="项目描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}