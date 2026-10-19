import { useEffect, useState } from 'react'
import { App as AntApp, Card, Descriptions, Tabs } from 'antd'
import { useParams } from 'react-router-dom'
import { apiGetWorkspace } from '../../api/workspaces'
import { apiErrorMessage } from '../../api/client'
import type { WorkspaceOut } from '../../api/types'
import { fmtTime } from '../../utils/format'
import ProjectsPanel from './ProjectsPanel'
import MembersPanel from './MembersPanel'
import PermissionGate from '../../components/PermissionGate'
import PageHeader from '../../components/PageHeader'
import { usePermissionStore } from '../../stores/permissionStore'

export default function WorkspaceDetail() {
  const { workspaceId } = useParams()
  const { message } = AntApp.useApp()
  const id = workspaceId ?? ''
  const [ws, setWs] = useState<WorkspaceOut | null>(null)
  const permissionCache = usePermissionStore((s) => s.cache)
  const loadPermissions = usePermissionStore((s) => s.load)

  useEffect(() => {
    if (!id) return
    void apiGetWorkspace(id)
      .then(setWs)
      .catch((e) => message.error(apiErrorMessage(e)))
    void loadPermissions({ workspaceId: id })
  }, [id])

  const ctx = { workspaceId: id }
  const wsPerms = permissionCache[`ws:${id}`] ?? []
  const canReadProjects = wsPerms.includes('project:read')
  const canManageMembers = wsPerms.includes('member:invite')

  const tabs = [
    ...(canReadProjects
      ? [{ key: 'projects', label: '爬虫项目', children: <ProjectsPanel workspaceId={id} /> }]
      : []),
    ...(canManageMembers
      ? [{ key: 'members', label: '成员管理', children: <MembersPanel workspaceId={id} /> }]
      : []),
  ]

  return (
    <div>
      <PageHeader title={`工作空间：${ws?.name ?? `#${id}`}`} description="该空间的爬虫项目与成员管理" />
      {ws && (
        <Card style={{ marginBottom: 16 }}>
          <Descriptions column={{ xs: 1, sm: 2, md: 4 }} size="small">
            <Descriptions.Item label="ID">{ws.id}</Descriptions.Item>
            <Descriptions.Item label="状态">{ws.status}</Descriptions.Item>
            <Descriptions.Item label="所有者 ID">{ws.owner_id}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{fmtTime(ws.created_at)}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}
      <Card>
        <PermissionGate ctx={ctx} permission={['project:read', 'member:invite']} mode="any">
          <Tabs items={tabs} />
        </PermissionGate>
      </Card>
    </div>
  )
}