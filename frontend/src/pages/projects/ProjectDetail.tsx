import { useEffect, useState } from 'react'
import { App as AntApp, Button, Card, Descriptions, Popconfirm, Tabs, Tag, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiDeleteProject, apiGetProject } from '../../api/projects'
import { apiErrorMessage } from '../../api/client'
import type { ProjectOut } from '../../api/types'
import { SOURCE_TYPE_LABELS } from '../../api/types'
import { fmtTime } from '../../utils/format'
import DevContainerPanel from './DevContainerPanel'
import RunPanel from './RunPanel'
import DataPanel from './DataPanel'
import LoginPanel from './LoginPanel'
import PermissionGate from '../../components/PermissionGate'
import PageHeader from '../../components/PageHeader'
import { usePermissionStore } from '../../stores/permissionStore'

export default function ProjectDetail() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const id = projectId ?? ''
  const [project, setProject] = useState<ProjectOut | null>(null)
  const permissionCache = usePermissionStore((s) => s.cache)
  const loadPermissions = usePermissionStore((s) => s.load)

  useEffect(() => {
    if (!id) return
    void apiGetProject(id)
      .then((p) => {
        setProject(p)
        void loadPermissions({ workspaceId: p.workspace_id })
      })
      .catch((e) => message.error(apiErrorMessage(e)))
  }, [id])

  const remove = async () => {
    try {
      await apiDeleteProject(id)
      message.success('已删除项目')
      navigate(`/workspaces/${project?.workspace_id ?? ''}`)
    } catch (e) {
      message.error(apiErrorMessage(e))
    }
  }

  const wsPerms = project ? (permissionCache[`ws:${project.workspace_id}`] ?? []) : []
  const canRun = wsPerms.includes('run:trigger')
  const canManageContainer = wsPerms.includes('container:manage')
  const canReadData = wsPerms.includes('data:read')
  const canTrigger = wsPerms.includes('run:trigger')
  const canDelete = wsPerms.includes('project:delete')

  const tabs = project
    ? [
        ...(canRun ? [{ key: 'runs', label: '运行', children: <RunPanel projectId={id} workspaceId={project.workspace_id} /> }] : []),
        ...(canManageContainer
          ? [{ key: 'container', label: '开发容器', children: <DevContainerPanel projectId={id} workspaceId={project.workspace_id} /> }]
          : []),
        ...(canReadData ? [{ key: 'data', label: '数据', children: <DataPanel projectId={id} workspaceId={project.workspace_id} /> }] : []),
        ...(canTrigger ? [{ key: 'login', label: 'login 实时画面', children: <LoginPanel projectId={id} workspaceId={project.workspace_id} /> }] : []),
      ]
    : []

  return (
    <div>
      <PageHeader
        title={`项目：${project?.name ?? `#${id}`}`}
        description="运行、开发容器、数据与 login 实时画面"
        extra={
          project && canDelete ? (
            <Popconfirm title="确定删除该项目？" onConfirm={() => void remove()}>
              <Button danger>删除项目</Button>
            </Popconfirm>
          ) : undefined
        }
      />

      {project && (
        <Card style={{ marginBottom: 16 }}>
          <Descriptions column={{ xs: 1, sm: 2, md: 3 }} size="small" bordered>
            <Descriptions.Item label="ID">{project.id}</Descriptions.Item>
            <Descriptions.Item label="工作空间 ID">{project.workspace_id}</Descriptions.Item>
            <Descriptions.Item label="来源">
              <Tag color={project.source_type === 'builtin' ? 'blue' : 'purple'}>
                {SOURCE_TYPE_LABELS[project.source_type] ?? project.source_type}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="crawler_id">
              <Typography.Text code>{project.crawler_id}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="内置爬取器 ID">{project.builtin_crawler_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={project.status === 'active' ? 'green' : 'default'}>{project.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">{fmtTime(project.created_at)}</Descriptions.Item>
            <Descriptions.Item label="描述" span={2}>
              {project.description ?? '-'}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      <Card>
        <PermissionGate
          ctx={{ workspaceId: project?.workspace_id }}
          permission={['run:trigger', 'container:manage', 'data:read']}
          mode="any"
        >
          <Tabs defaultActiveKey="runs" items={tabs} />
        </PermissionGate>
      </Card>
    </div>
  )
}