import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { App as AntApp, ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useThemeStore } from './stores/themeStore'
import AuthGuard from './components/AuthGuard'
import AppLayout from './components/AppLayout'
import PermissionGate from './components/PermissionGate'
import Login from './pages/auth/Login'
import Register from './pages/auth/Register'
import Dashboard from './pages/Dashboard'
import WorkspacesList from './pages/workspaces/WorkspacesList'
import WorkspaceDetail from './pages/workspaces/WorkspaceDetail'
import ProjectDetail from './pages/projects/ProjectDetail'
import RunDetail from './pages/runs/RunDetail'
import AuditLogs from './pages/audit/AuditLogs'
import NotFound from './pages/NotFound'

export default function App() {
  const resolved = useThemeStore((s) => s.resolved)

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: resolved === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
      }}
    >
      <AntApp>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route
              element={
                <AuthGuard>
                  <AppLayout />
                </AuthGuard>
              }
            >
              <Route path="/" element={<Dashboard />} />
              <Route path="/workspaces" element={<WorkspacesList />} />
              <Route path="/workspaces/:workspaceId" element={<WorkspaceDetail />} />
              <Route path="/projects/:projectId" element={<ProjectDetail />} />
              <Route path="/runs/:runId" element={<RunDetail />} />
              <Route
                path="/audit"
                element={
                  <PermissionGate permission="audit:read">
                    <AuditLogs />
                  </PermissionGate>
                }
              />
            </Route>
            <Route path="/404" element={<NotFound />} />
            <Route path="*" element={<Navigate to="/404" replace />} />
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}