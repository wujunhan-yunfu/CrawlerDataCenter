import { Typography } from 'antd'

interface Props {
  title: React.ReactNode
  description?: React.ReactNode
  /** 右侧操作区, 通常放主按钮 / 筛选器 */
  extra?: React.ReactNode
}

/** 菜单页面统一的标题区: 左标题+描述, 右操作(参考 DeepSeek 平台用量页)。 */
export default function PageHeader({ title, description, extra }: Props) {
  return (
    <div className="cdc-page-header">
      <div className="cdc-page-header-main">
        <Typography.Title level={4} className="cdc-page-header-title">
          {title}
        </Typography.Title>
        {description && (
          <Typography.Text type="secondary" className="cdc-page-header-desc">
            {description}
          </Typography.Text>
        )}
      </div>
      {extra && <div className="cdc-page-header-extra">{extra}</div>}
    </div>
  )
}
