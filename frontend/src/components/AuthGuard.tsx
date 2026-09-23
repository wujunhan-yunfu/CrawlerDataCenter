import { useEffect } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuthStore } from '../stores/authStore'

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, loading, bootstrapped, bootstrap } = useAuthStore()
  const location = useLocation()

  useEffect(() => {
    if (!bootstrapped) {
      void bootstrap()
    }
  }, [bootstrapped, bootstrap])

  if (!bootstrapped || loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }

  return <>{children}</>
}