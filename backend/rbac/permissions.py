"""权限点定义与内置角色。"""

from __future__ import annotations

# 权限点
PERMISSIONS = {
    # workspace
    "workspace:create",
    "workspace:read",
    "workspace:update",
    "workspace:delete",
    # member
    "member:invite",
    "member:remove",
    "member:update_role",
    # project
    "project:create",
    "project:read",
    "project:update",
    "project:delete",
    # code (自定义代码)
    "code:read",
    "code:edit",
    "code:commit",
    "code:checkout",
    # credential
    "credential:read",
    "credential:write",
    # run
    "run:trigger",
    "run:read",
    "container:manage",
    # data
    "data:read",
    # audit
    "audit:read",
}

# 内置角色 -> 权限
BUILTIN_ROLES: dict[str, dict] = {
    "super_admin": {
        "scope": "global",
        "description": "平台管理员, 全部权限",
        "permissions": set(PERMISSIONS) | {"member:invite"},
    },
    "workspace_owner": {
        "scope": "workspace",
        "description": "工作空间所有者, 管理成员与全部项目",
        "permissions": {
            "workspace:read", "workspace:update", "workspace:delete",
            "member:invite", "member:remove", "member:update_role",
            "project:create", "project:read", "project:update", "project:delete",
            "code:read", "code:edit", "code:commit", "code:checkout",
            "credential:read", "credential:write",
            "run:trigger", "run:read", "container:manage",
            "data:read", "audit:read",
        },
    },
    "workspace_admin": {
        "scope": "workspace",
        "description": "工作空间管理员, 管理项目与成员(不含删除空间)",
        "permissions": {
            "workspace:read", "workspace:update",
            "member:invite", "member:remove", "member:update_role",
            "project:create", "project:read", "project:update", "project:delete",
            "code:read", "code:edit", "code:commit", "code:checkout",
            "credential:read", "credential:write",
            "run:trigger", "run:read", "container:manage",
            "data:read", "audit:read",
        },
    },
    "developer": {
        "scope": "workspace",
        "description": "创建/编辑代码、提交版本、触发 login 运行",
        "permissions": {
            "project:read",
            "code:read", "code:edit", "code:commit", "code:checkout",
            "credential:read", "credential:write",
            "run:trigger", "run:read", "container:manage",
            "data:read",
        },
    },
    "operator": {
        "scope": "workspace",
        "description": "触发 run、查看运行记录与数据, 不可改代码",
        "permissions": {
            "project:read",
            "code:read",
            "credential:read",
            "run:trigger", "run:read",
            "data:read",
        },
    },
    "viewer": {
        "scope": "workspace",
        "description": "只读",
        "permissions": {
            "project:read",
            "code:read",
            "credential:read",
            "run:read",
            "data:read",
        },
    },
}