import { Segmented } from 'antd'
import { DesktopOutlined, MoonOutlined, SunOutlined } from '@ant-design/icons'
import { useThemeStore, type ThemeMode } from '../stores/themeStore'

interface Props {
  size?: 'small' | 'middle' | 'large'
}

/** 明暗主题切换: 跟随系统 / 浅色 / 深色, 默认跟随系统。 */
export default function ThemeToggle({ size = 'middle' }: Props) {
  const mode = useThemeStore((s) => s.mode)
  const setMode = useThemeStore((s) => s.setMode)

  return (
    <Segmented<ThemeMode>
      size={size}
      value={mode}
      shape="round"
      onChange={(value) => setMode(value)}
      options={[
        { value: 'system', icon: <DesktopOutlined />, tooltip: '跟随系统' },
        { value: 'light', icon: <SunOutlined />, tooltip: '浅色' },
        { value: 'dark', icon: <MoonOutlined />, tooltip: '深色' },
      ]}
    />
  )
}
