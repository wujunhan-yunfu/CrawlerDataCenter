import { useState } from 'react'
import { Alert, Button, Form, Input, Typography } from 'antd'
import { LockOutlined, MailOutlined, UserOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { apiErrorMessage } from '../../api/client'
import AuthLayout from '../../components/AuthLayout'

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
    <AuthLayout>
      <div style={{ textAlign: 'center' }}>
        <div className="cdc-auth-logo">
          <img src="/favicon.svg" alt="Crawler Data Center" width={46} height={44} />
        </div>
        <Typography.Title level={3} style={{ marginBottom: 8 }}>
          创建账号
        </Typography.Title>
        <Typography.Text type="secondary">加入爬虫数据中心控制台</Typography.Text>
      </div>

      {error && <Alert type="error" message={error} showIcon style={{ marginTop: 24 }} />}

      <Form<RegisterForm> onFinish={onFinish} layout="vertical" size="large" requiredMark={false} style={{ marginTop: 28 }}>
        <Form.Item
          name="username"
          rules={[
            { required: true, message: '请输入用户名' },
            { min: 3, max: 64, message: '用户名长度为 3-64 字符' },
          ]}
        >
          <Input variant="filled" prefix={<UserOutlined />} placeholder="用户名（3-64 字符）" autoComplete="username" />
        </Form.Item>
        <Form.Item
          name="email"
          rules={[
            { required: true, message: '请输入邮箱' },
            { type: 'email', message: '邮箱格式不正确' },
          ]}
        >
          <Input variant="filled" prefix={<MailOutlined />} placeholder="邮箱" autoComplete="email" />
        </Form.Item>
        <Form.Item
          name="password"
          rules={[
            { required: true, message: '请输入密码' },
            { min: 8, max: 128, message: '密码长度至少 8 位' },
          ]}
        >
          <Input.Password
            variant="filled"
            prefix={<LockOutlined />}
            placeholder="密码（至少 8 位）"
            autoComplete="new-password"
          />
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
          <Input.Password variant="filled" prefix={<LockOutlined />} placeholder="确认密码" autoComplete="new-password" />
        </Form.Item>
        <Form.Item style={{ marginBottom: 12 }}>
          <Button type="primary" htmlType="submit" block loading={submitting} className="cdc-auth-submit">
            注册
          </Button>
        </Form.Item>
      </Form>

      <div style={{ textAlign: 'center', marginTop: 8 }}>
        <Typography.Text type="secondary">已有账号？</Typography.Text> <Link to="/login">去登录</Link>
      </div>
    </AuthLayout>
  )
}
