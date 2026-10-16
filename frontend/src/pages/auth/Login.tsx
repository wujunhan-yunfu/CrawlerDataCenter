import { useState } from 'react'
import { Alert, Button, Form, Input, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { apiErrorMessage } from '../../api/client'
import AuthLayout from '../../components/AuthLayout'

interface LoginForm {
  username: string
  password: string
}

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const login = useAuthStore((s) => s.login)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const from = (location.state as { from?: string } | null)?.from ?? '/'

  const onFinish = async (values: LoginForm) => {
    setSubmitting(true)
    setError(null)
    try {
      await login(values)
      navigate(from, { replace: true })
    } catch (e) {
      setError(apiErrorMessage(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout>
      <div style={{ textAlign: 'center' }}>
        {/* 参考 DeepSeek 登录页: 原二维码登录框位置替换为品牌 Logo */}
        <div className="cdc-auth-logo">
          <img src="/favicon.svg" alt="Crawler Data Center" width={46} height={44} />
        </div>
        <Typography.Title level={3} style={{ marginBottom: 8 }}>
          欢迎回来
        </Typography.Title>
        <Typography.Text type="secondary">登录爬虫数据中心控制台</Typography.Text>
      </div>

      {error && <Alert type="error" message={error} showIcon style={{ marginTop: 24 }} />}

      <Form<LoginForm> onFinish={onFinish} layout="vertical" size="large" requiredMark={false} style={{ marginTop: 28 }}>
        <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
          <Input variant="filled" prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
        </Form.Item>
        <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
          <Input.Password
            variant="filled"
            prefix={<LockOutlined />}
            placeholder="密码"
            autoComplete="current-password"
          />
        </Form.Item>
        <Form.Item style={{ marginBottom: 12 }}>
          <Button type="primary" htmlType="submit" block loading={submitting} className="cdc-auth-submit">
            登录
          </Button>
        </Form.Item>
      </Form>

      <div style={{ textAlign: 'center', marginTop: 8 }}>
        <Typography.Text type="secondary">还没有账号？</Typography.Text> <Link to="/register">立即注册</Link>
      </div>
    </AuthLayout>
  )
}
