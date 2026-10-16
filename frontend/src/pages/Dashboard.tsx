import { useEffect } from 'react'
import { Card, Col, List, Row, Statistic, Tag, Typography } from 'antd'
import { ApiOutlined, CheckCircleOutlined, DatabaseOutlined, ProjectOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../stores/appStore'
import { fmtTime } from '../utils/format'
import PageHeader from '../components/PageHeader'

export default function Dashboard() {
  const navigate = useNavigate()
  const { workspaces, health, loadWorkspaces } = useAppStore()

  useEffect(() => {
    void loadWorkspaces().catch(() => undefined)
  }, [loadWorkspaces])

  return (
    <div>
      <PageHeader title="总览" description="服务健康状态与工作空间概览" />
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="工作空间" value={workspaces.length} prefix={<ApiOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="数据库"
              value={health?.db ? '正常' : '异常'}
              valueStyle={{ color: health?.db ? '#3f8600' : '#cf1322' }}
              prefix={<DatabaseOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Redis"
              value={health?.redis ? '正常' : '异常'}
              valueStyle={{ color: health?.redis ? '#3f8600' : '#cf1322' }}
              prefix={<DatabaseOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="整体状态"
              value={health?.ok ? '正常' : '异常'}
              valueStyle={{ color: health?.ok ? '#3f8600' : '#cf1322' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card title="我的工作空间" style={{ marginTop: 16 }}>
        <List
          dataSource={workspaces}
          locale={{ emptyText: '暂无工作空间，请先创建' }}
          renderItem={(ws) => (
            <List.Item
              actions={[
                <Typography.Link key="open" onClick={() => navigate(`/workspaces/${ws.id}`)}>
                  进入
                </Typography.Link>,
              ]}
            >
              <List.Item.Meta
                avatar={<ProjectOutlined style={{ fontSize: 20 }} />}
                title={ws.name}
                description={
                  <span>
                    <Tag color={ws.status === 'active' ? 'green' : 'default'}>{ws.status}</Tag>
                    创建于 {fmtTime(ws.created_at)}
                  </span>
                }
              />
            </List.Item>
          )}
        />
      </Card>
    </div>
  )
}