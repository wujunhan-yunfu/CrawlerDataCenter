import { useEffect } from 'react'
import { Avatar, Badge, Dropdown, Layout, Menu, Space, Typography, theme } from 'antd'
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
import ThemeToggle from './ThemeToggle'

const { Header, Content } = Layout

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { health, refreshHealth } = useAppStore()
  const { token } = theme.useToken()
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
      <Header
        className="cdc-topbar"
        style={{
          background: token.colorBgContainer,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <div className="cdc-topbar-inner">
          <div className="cdc-brand" role="button" onClick={() => navigate('/')}>
            <img src="/favicon.svg" alt="Crawler Data Center" width={26} height={25} />
            <span className="cdc-brand-text">Crawler Data Center</span>
          </div>

          <Menu
            className="cdc-nav"
            mode="horizontal"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ borderBottom: 'none', background: 'transparent', flex: 1, minWidth: 0 }}
          />

          <Space size={16} className="cdc-topbar-actions">
            <Space size={6} className="cdc-health">
              <Badge status={health?.ok ? 'success' : 'error'} />
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {health?.ok ? '服务正常' : '服务异常'}
              </Typography.Text>
            </Space>
            <ThemeToggle size="small" />
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
              <Space size={8} style={{ cursor: 'pointer' }}>
                <Avatar size="small" icon={<UserOutlined />} />
                <span className="cdc-user-name">{user?.username}</span>
              </Space>
            </Dropdown>
          </Space>
        </div>
      </Header>

      <Content className="cdc-content">
        <div className="cdc-content-inner">
          <Outlet />
        </div>
      </Content>
    </Layout>
  )
}
