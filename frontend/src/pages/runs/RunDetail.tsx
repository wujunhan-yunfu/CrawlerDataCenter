import { useEffect, useState } from 'react'
import { App as AntApp, Card, Descriptions, Table, Tag, Typography } from 'antd'
import { useParams } from 'react-router-dom'
import { apiGetRunDetail } from '../../api/runs'
import { apiErrorMessage } from '../../api/client'
import type { RunDetailOut } from '../../api/types'
import { fmtDuration, fmtTime } from '../../utils/format'
import { MODE_LABELS, RUN_STATUS_COLORS, TRIGGER_LABELS } from '../../api/types'

export default function RunDetail() {
  const { runId } = useParams()
  const { message } = AntApp.useApp()
  const [run, setRun] = useState<RunDetailOut | null>(null)

  useEffect(() => {
    if (!runId) return
    void apiGetRunDetail(runId)
      .then(setRun)
      .catch((e) => message.error(apiErrorMessage(e)))
  }, [runId])

  if (!run) return null

  const savedRows = (run.saved ?? []).map((item, idx) => ({ key: idx, ...(item as Record<string, unknown>) }))
  const savedColumns = Object.keys(savedRows[0] ?? {}).map((k) => ({
    title: k,
    dataIndex: k,
    key: k,
    ellipsis: true,
    render: (v: unknown) => {
      if (v === null || v === undefined) return '-'
      if (typeof v === 'object') return <Typography.Text code>{JSON.stringify(v)}</Typography.Text>
      return String(v)
    },
  }))

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        运行详情：<Typography.Text code>{run.run_id}</Typography.Text>
      </Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        <Descriptions column={{ xs: 1, sm: 2, md: 3 }} size="small" bordered>
          <Descriptions.Item label="项目 ID">{run.project_id}</Descriptions.Item>
          <Descriptions.Item label="工作空间 ID">{run.workspace_id}</Descriptions.Item>
          <Descriptions.Item label="crawler_id">
            <Typography.Text code>{run.crawler_id}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="模式">{MODE_LABELS[run.mode] ?? run.mode}</Descriptions.Item>
          <Descriptions.Item label="触发">{TRIGGER_LABELS[run.trigger] ?? run.trigger}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={RUN_STATUS_COLORS[run.status] ?? 'default'}>{run.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Cron">{run.cron ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="开始时间">{fmtTime(run.started_at)}</Descriptions.Item>
          <Descriptions.Item label="结束时间">{fmtTime(run.finished_at)}</Descriptions.Item>
          <Descriptions.Item label="耗时">{fmtDuration(run.duration_ms)}</Descriptions.Item>
          <Descriptions.Item label="定时进程">{run.process_id ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="错误信息" span={3}>
            {run.error_json ? <Typography.Text code>{JSON.stringify(run.error_json)}</Typography.Text> : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title={`入库数据 (${savedRows.length})`} size="small">
        {savedRows.length === 0 ? (
          <Typography.Text type="secondary">本次运行暂无入库数据。</Typography.Text>
        ) : (
          <Table
            dataSource={savedRows}
            columns={savedColumns}
            pagination={false}
            scroll={{ x: 'max-content' }}
            size="small"
          />
        )}
      </Card>
    </div>
  )
}