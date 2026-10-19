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
  Table,
  Tag,
  Typography,
} from 'antd'
import { UserAddOutlined } from '@ant-design/icons'
import type { MemberOut } from '../../api/types'
import { apiAddMember, apiListMembers, apiRemoveMember } from '../../api/workspaces'
import { apiErrorMessage } from '../../api/client'
import { ROLE_LABELS } from '../../api/types'
import PermissionGate from '../../components/PermissionGate'
import { usePermissionStore } from '../../stores/permissionStore'

interface Props {
  workspaceId: string
}

interface MemberForm {
  username: string
  role: string
}

export default function MembersPanel({ workspaceId }: Props) {
  const { message } = AntApp.useApp()
  const [items, setItems] = useState<MemberOut[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm<MemberForm>()
  const permissionCache = usePermissionStore((s) => s.cache)
  const loadPermissions = usePermissionStore((s) => s.load)

  const load = async () => {
    setLoading(true)
    try {
      setItems(await apiListMembers(workspaceId))
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

  const submit = async () => {
    const values = await form.validateFields()
    try {
      await apiAddMember(workspaceId, values)
      message.success('已添加成员')
      setModalOpen(false)
      form.resetFields()
      void load()
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  const remove = async (userId: string) => {
    try {
      await apiRemoveMember(workspaceId, userId)
      message.success('已移除成员')
      void load()
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  return (
    <div>
      <Card
        extra={
          <PermissionGate ctx={{ workspaceId }} permission="member:invite">
            <Button type="primary" icon={<UserAddOutlined />} onClick={() => setModalOpen(true)}>
              邀请成员
            </Button>
          </PermissionGate>
        }
      >
        <Table<MemberOut>
          rowKey="user_id"
          loading={loading}
          dataSource={items}
          pagination={false}
          columns={[
            { title: '用户 ID', dataIndex: 'user_id', width: 100 },
            { title: '用户名', dataIndex: 'username' },
            { title: '角色', dataIndex: 'role', width: 150, render: (r: string) => ROLE_LABELS[r] ?? r },
            {
              title: '范围',
              dataIndex: 'scope',
              width: 130,
              render: (s: string) => <Tag color={s === 'workspace' ? 'blue' : 'orange'}>{s === 'workspace' ? '空间级' : '项目级'}</Tag>,
            },
            { title: '项目 ID', dataIndex: 'project_id', width: 100, render: (v: string | null) => v ?? '-' },
            {
              title: '操作',
              key: 'actions',
              width: 100,
              render: (_, record) => {
                const canRemove = permissionCache[`ws:${workspaceId}`]?.includes('member:remove')
                if (!canRemove) return null
                return (
                  <Popconfirm title="确定移除该成员？" onConfirm={() => void remove(record.user_id)}>
                    <Typography.Link type="danger">移除</Typography.Link>
                  </Popconfirm>
                )
              },
            },
          ]}
        />
      </Card>

      <Modal
        title="邀请成员"
        open={modalOpen}
        onOk={() => void submit()}
        onCancel={() => setModalOpen(false)}
        okText="邀请"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" initialValues={{ role: 'developer' }}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入要邀请的用户名' }]}
          >
            <Input placeholder="用户用户名" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'workspace_admin', label: '空间管理员' },
                { value: 'developer', label: '开发者' },
                { value: 'operator', label: '运维' },
                { value: 'viewer', label: '只读' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}