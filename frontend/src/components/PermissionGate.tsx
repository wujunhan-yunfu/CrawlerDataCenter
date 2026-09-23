import { useEffect } from 'react'
import { Result } from 'antd'
import { ctxKey, usePermissionStore, type PermissionCtx } from '../stores/permissionStore'

export function NoPermission({ title = '无权限' }: { title?: string }) {
  return <Result status="403" title={title} subTitle="当前账号没有执行该操作的权限，如有疑问请联系空间管理员。" />
}

interface Props {
  ctx?: PermissionCtx
  permission: string | string[]
  /** all = 需全部权限(默认), any = 满足任一即可 */
  mode?: 'all' | 'any'
  fallback?: React.ReactNode
  children: React.ReactNode
}

export default function PermissionGate({ ctx, permission, mode = 'all', fallback, children }: Props) {
  const cache = usePermissionStore((s) => s.cache)
  const load = usePermissionStore((s) => s.load)

  useEffect(() => {
    void load(ctx)
  }, [load, ctx])

  const key = ctxKey(ctx)
  const loaded = key in cache
  const perms = cache[key] ?? []
  const required = Array.isArray(permission) ? permission : [permission]
  const allowed = mode === 'all' ? required.every((p) => perms.includes(p)) : required.some((p) => perms.includes(p))

  if (!loaded) return null
  if (!allowed) return <>{fallback ?? <NoPermission />}</>
  return <>{children}</>
}