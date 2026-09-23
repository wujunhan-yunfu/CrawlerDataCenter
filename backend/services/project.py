"""爬虫项目服务。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ids import snowflake_id, new_xid
from ..db.models import CrawlerProject, Workspace


def allocate_crawler_id() -> str:
    """custom 项目分配唯一 crawler_id(与 ACS --crawler-id 对齐)。"""
    return f"proj_{new_xid('')[4:]}{snowflake_id() & 0xFFFFFF:06x}"


class ProjectService:
    @staticmethod
    async def create(
        session: AsyncSession,
        ws_id: int,
        name: str,
        source_type: str = "custom",
        description: str | None = None,
        builtin_crawler_id: str | None = None,
        run_config: dict | None = None,
    ) -> CrawlerProject:
        if source_type == "builtin" and not builtin_crawler_id:
            raise ValueError("builtin 项目必须指定 builtin_crawler_id")
        project = CrawlerProject(
            id=snowflake_id(),
            workspace_id=ws_id,
            name=name,
            description=description,
            source_type=source_type,
            builtin_crawler_id=builtin_crawler_id,
            crawler_id=allocate_crawler_id() if source_type == "custom" else builtin_crawler_id,
            run_config_json=run_config,
        )
        session.add(project)
        await session.commit()
        return project

    @staticmethod
    async def list(session: AsyncSession, ws_id: int, offset: int = 0, limit: int = 50) -> tuple[list[CrawlerProject], int]:
        stmt = select(CrawlerProject).where(
            CrawlerProject.workspace_id == ws_id, CrawlerProject.deleted_at.is_(None)
        )
        total = await session.scalar(select(func.count(CrawlerProject.id)).where(CrawlerProject.workspace_id == ws_id, CrawlerProject.deleted_at.is_(None))) or 0
        rows = (await session.execute(stmt.order_by(CrawlerProject.id.desc()).offset(offset).limit(limit))).scalars().all()
        return list(rows), total

    @staticmethod
    async def get(session: AsyncSession, project_id: int) -> CrawlerProject | None:
        project = await session.get(CrawlerProject, project_id)
        if project is None or project.deleted_at is not None:
            return None
        return project

    @staticmethod
    async def update(
        session: AsyncSession,
        project: CrawlerProject,
        name: str | None,
        description: str | None,
        run_config: dict | None,
        status: str | None,
    ) -> CrawlerProject:
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if run_config is not None:
            project.run_config_json = run_config
        if status is not None:
            project.status = status
        await session.commit()
        return project

    @staticmethod
    async def delete(session: AsyncSession, project: CrawlerProject) -> None:
        project.soft_delete()
        project.status = "disabled"
        await session.commit()

    @staticmethod
    async def count_active_containers(session: AsyncSession, ws_id: int) -> int:
        """空间内处于 pending/starting/ready 的 dev 容器数(配额校验用)。"""
        from ..db.models import DevContainer

        return await session.scalar(
            select(func.count(DevContainer.id)).where(
                DevContainer.workspace_id == ws_id,
                DevContainer.phase.in_(("pending", "starting", "ready")),
            )
        ) or 0

    @staticmethod
    async def workspace(session: AsyncSession, project: CrawlerProject) -> Workspace | None:
        return await session.get(Workspace, project.workspace_id)