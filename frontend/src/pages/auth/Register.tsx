import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { apiErrorMessage } from '../../api/client'

interface RegisterForm {
  username: string
  email: string
  password: string
  confirm: string
}

export default function Register() {
  const navigate = useNavigate()
  const register = useAuthStore((s) => s.register)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onFinish = async (values: RegisterForm) => {
    setSubmitting(true)
    setError(null)
    try {
      await register({ username: values.username, email: values.email, password: values.password })
      navigate('/', { replace: true })
    } catch (e) {
      setError(apiErrorMessage(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        overflowY: 'auto',
        background: 'linear-gradient(135deg, #1f2937 0%, #111827 100%)',
      }}
    >
      <Card style={{ width: 380, margin: 'auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Typography.Title level={3} style={{ marginBottom: 4 }}>
            注册账号
          </Typography.Title>
          <Typography.Text type="secondary">创建你的爬虫数据中心账号</Typography.Text>
        </div>
        {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}
        <Form<RegisterForm> onFinish={onFinish} size="large" layout="vertical">
          <Form.Item
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 3, max: 64, message: '用户名长度为 3-64 字符' },
            ]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名（3-64 字符）" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="email"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input prefix={<MailOutlined />} placeholder="邮箱" autoComplete="email" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 8, max: 128, message: '密码长度至少 8 位' },
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码（至少 8 位）" autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入密码' },
              ({ getFieldValue }) => ({
                validator: (_, value) =>
                  !value || getFieldValue('password') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致')),
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="确认密码" autoComplete="new-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 12 }}>
            <Button type="primary" htmlType="submit" block loading={submitting}>
              注册
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center' }}>
          已有账号？<Link to="/login">去登录</Link>
        </div>
      </Card>
    </div>
  )
}