import { useEffect } from 'react'
import { Avatar, Dropdown, Layout, Menu, Space, Tag, Typography } from 'antd'
import {
  AppstoreOutlined,
  DashboardOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { useAppStore } from '../stores/appStore'
import { usePermissionStore } from '../stores/permissionStore'

const { Header, Sider, Content } = Layout

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { health, refreshHealth } = useAppStore()
  const permissionCache = usePermissionStore((s) => s.cache)
  const loadPermissions = usePermissionStore((s) => s.load)

  useEffect(() => {
    void refreshHealth()
    const timer = setInterval(() => {
      void refreshHealth()
    }, 30000)
    return () => clearInterval(timer)
  }, [refreshHealth])

  useEffect(() => {
    void loadPermissions()
  }, [loadPermissions])

  const globalPerms = permissionCache.global ?? []
  const canAudit = globalPerms.includes('audit:read')

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '总览' },
    { key: '/workspaces', icon: <AppstoreOutlined />, label: '工作空间' },
    ...(canAudit ? [{ key: '/audit', icon: <FileSearchOutlined />, label: '审计日志' }] : []),
  ]

  const selectedKey = location.pathname.startsWith('/workspaces')
    ? '/workspaces'
    : location.pathname.startsWith('/audit')
      ? '/audit'
      : '/'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={220} theme="dark">
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 16,
            fontWeight: 600,
            letterSpacing: 1,
          }}
        >
          Crawler Data Center
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
          }}
        >
          <Space size={12}>
            <Typography.Text strong>{user?.username ?? ''}</Typography.Text>
            <Tag color={health?.ok ? 'green' : 'red'}>{health?.ok ? '服务正常' : '服务异常'}</Tag>
          </Space>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: '退出登录',
                  onClick: () => {
                    void logout().then(() => navigate('/login'))
                  },
                },
              ],
            }}
          >
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{user?.username}</span>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}