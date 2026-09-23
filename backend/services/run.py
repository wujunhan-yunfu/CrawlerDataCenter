"""运行触发与查询服务: once/cron 创建 K8s Job/Deployment, login 触发, 运行记录查询。"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.ids import new_run_id, snowflake_id
from ..db.models import CrawlerProject, Run, RunProcess, RunResult
from ..k8s.client import KubeClient
from ..k8s.templates import build_run_deployment, build_run_job, pod_name_for
from ..services.cron import validate_cron


class RunService:
    def __init__(self, kube: KubeClient) -> None:
        self.kube = kube

    def _webhook_base(self) -> str:
        base = settings.run_webhook_base
        if not base:
            base = "http://127.0.0.1:8080/api/v1"
        return base.rstrip("/")

    def _run_env(self, project: CrawlerProject, run_id: str, trigger: str, cron: str | None, headless: bool) -> dict:
        base = self._webhook_base()
        return {
            "MODE": "run",
            "CRAWLER_ID": project.crawler_id,
            "RUN_ID": run_id,
            "PROJECT_ID": str(project.id),
            "WORKSPACE_ID": str(project.workspace_id),
            "RUN_TYPE": trigger,
            "CRON": cron or "",
            "HEADLESS": "1" if headless else "0",
            "SOURCE": "mongo",
            "WEBHOOK_URL": f"{base}/webhooks/runs",
            "HEARTBEAT_INTERVAL": str(settings.heartbeat_interval),
            "DATA_WEBHOOK_URL": f"{base}/webhooks/data",
        }

    async def trigger_once(
        self,
        session: AsyncSession,
        project: CrawlerProject,
        headless: bool = True,
        webhook_secret: str | None = None,
    ) -> Run:
        run_id = new_run_id()
        run = Run(
            id=snowflake_id(),
            run_id=run_id,
            project_id=project.id,
            crawler_id=project.crawler_id,
            workspace_id=project.workspace_id,
            mode="run",
            trigger="once",
            run_type="once",
            status="pending",
            started_at=int(time.time() * 1000),
        )
        session.add(run)
        await session.commit()

        env = self._run_env(project, run_id, "once", None, headless)
        if webhook_secret:
            env["WEBHOOK_SECRET"] = webhook_secret
        job = build_run_job(project.crawler_id, settings.k8s_namespace, env, settings.acs_image)
        await self.kube.create_run_job(job)
        return run

    async def trigger_cron(
        self,
        session: AsyncSession,
        project: CrawlerProject,
        cron: str,
        headless: bool = True,
        webhook_secret: str | None = None,
    ) -> RunProcess:
        if not validate_cron(cron):
            raise ValueError(f"cron 表达式无效: {cron}")

        process = await session.scalar(
            select(RunProcess).where(RunProcess.project_id == project.id)
        )
        if process is None:
            process = RunProcess(
                id=snowflake_id(),
                process_id=new_run_id().replace("run_", "proc_")[:14],
                project_id=project.id,
                crawler_id=project.crawler_id,
                workspace_id=project.workspace_id,
                run_type="cron",
                cron=cron,
                status="alive",
                started_at=int(time.time() * 1000),
            )
            session.add(process)
        else:
            process.cron = cron
            process.status = "alive"
        await session.commit()

        env = self._run_env(project, process.process_id, "cron", cron, headless)
        if webhook_secret:
            env["WEBHOOK_SECRET"] = webhook_secret
        deploy = build_run_deployment(project.crawler_id, settings.k8s_namespace, env, settings.acs_image)
        await self.kube.create_run_deployment(deploy)
        process.pod_name = pod_name_for(project.crawler_id, role="run")
        await session.commit()
        return process

    async def stop_cron(self, session: AsyncSession, project: CrawlerProject) -> RunProcess | None:
        process = await session.scalar(
            select(RunProcess).where(RunProcess.project_id == project.id)
        )
        if process:
            await self.kube.delete_deployment(
                pod_name_for(project.crawler_id, role="run"), settings.k8s_namespace
            )
            process.status = "stopped"
            await session.commit()
        return process

    async def login_trigger(
        self, session: AsyncSession, project: CrawlerProject, headless: bool = False
    ) -> Run:
        run_id = new_run_id()
        run = Run(
            id=snowflake_id(),
            run_id=run_id,
            project_id=project.id,
            crawler_id=project.crawler_id,
            workspace_id=project.workspace_id,
            mode="login",
            trigger="once",
            run_type="once",
            status="pending",
            started_at=int(time.time() * 1000),
        )
        session.add(run)
        await session.commit()
        return run

    # ---- 查询 ----

    async def list_runs(
        self,
        session: AsyncSession,
        project_id: int | None = None,
        workspace_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Run], int]:
        stmt = select(Run)
        if project_id is not None:
            stmt = stmt.where(Run.project_id == project_id)
        if workspace_id is not None:
            stmt = stmt.where(Run.workspace_id == workspace_id)
        total = await session.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0
        rows = (
            await session.execute(stmt.order_by(Run.id.desc()).offset(offset).limit(limit))
        ).scalars().all()
        return list(rows), total

    async def get_run(self, session: AsyncSession, run_id: str) -> Run | None:
        return await session.scalar(select(Run).where(Run.run_id == run_id))

    async def get_run_detail(self, session: AsyncSession, run_id: str) -> dict | None:
        run = await self.get_run(session, run_id)
        if run is None:
            return None
        saved = (
            await session.execute(select(RunResult).where(RunResult.run_id == run_id))
        ).scalars().all()
        return {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "crawler_id": run.crawler_id,
            "workspace_id": run.workspace_id,
            "mode": run.mode,
            "trigger": run.trigger,
            "cron": run.cron,
            "process_id": run.process_id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_ms": run.duration_ms,
            "error_json": run.error_json,
            "saved": [
                {
                    "name": r.name,
                    "kind": r.kind,
                    "size": r.size,
                    "save_id": r.save_id,
                    "delivery": r.delivery,
                    "remote_path": r.remote_path,
                }
                for r in saved
            ],
        }

    async def get_process(self, session: AsyncSession, project_id: int) -> RunProcess | None:
        return await session.scalar(select(RunProcess).where(RunProcess.project_id == project_id))