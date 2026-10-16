import { ConfigProvider, theme as antdTheme } from 'antd'
import { useThemeStore } from '../stores/themeStore'
import ThemeToggle from './ThemeToggle'

/** 参考 DeepSeek 登录页的品牌主色。 */
const BRAND_PRIMARY = '#4d6bfe'

interface Props {
  children: React.ReactNode
}

/**
 * 认证页(登录/注册)共用布局:
 * 全屏居中、极简背景 + 顶部主题切换, 主色与圆角参考 DeepSeek 风格。
 */
export default function AuthLayout({ children }: Props) {
  const resolved = useThemeStore((s) => s.resolved)

  return (
    <ConfigProvider
      theme={{
        algorithm: resolved === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: BRAND_PRIMARY,
          borderRadius: 10,
          controlHeight: 44,
          fontSize: 15,
        },
      }}
    >
      <div className="cdc-auth">
        <div className="cdc-auth-toggle">
          <ThemeToggle />
        </div>

        <main className="cdc-auth-panel">{children}</main>

        <footer className="cdc-auth-footer">© {new Date().getFullYear()} Crawler Data Center</footer>
      </div>
    </ConfigProvider>
  )
}
