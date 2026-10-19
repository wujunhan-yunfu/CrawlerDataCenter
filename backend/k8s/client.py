"""K8s 客户端抽象接口。

生产环境安装 `kubernetes` 依赖后实现 RealKubeClient; 测试使用 FakeKubeClient。
所有编排逻辑(services/dev_container.py)只依赖本接口, 便于单测与后续集群切换。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PodStatus:
    name: str
    phase: str          # Pending / Running / Succeeded / Failed / Unknown
    ready: bool
    reason: str | None = None


@dataclass
class CreateResult:
    pod_name: str
    service_name: str | None = None


class KubeClient(ABC):
    @abstractmethod
    async def create_dev_pod(self, pod_spec: dict, service_spec: dict | None = None) -> CreateResult:
        """创建 dev Pod(和可选 Service), 返回名称。"""

    @abstractmethod
    async def get_pod_status(self, name: str, namespace: str) -> PodStatus:
        """查询 Pod 状态(用于就绪探针轮询)。"""

    @abstractmethod
    async def delete_pod(self, name: str, namespace: str) -> None:
        ...

    @abstractmethod
    async def delete_service(self, name: str, namespace: str) -> None:
        ...

    @abstractmethod
    async def create_run_job(self, job_spec: dict) -> None:
        """创建一次性 run Job。"""

    @abstractmethod
    async def create_run_deployment(self, deploy_spec: dict) -> None:
        """创建/更新 cron 常驻 run Deployment。"""

    @abstractmethod
    async def delete_deployment(self, name: str, namespace: str) -> None:
        ...

    @abstractmethod
    async def proxy_ws(self, pod_name: str, namespace: str, path: str, port: int) -> dict:
        """发起到 Pod 的 WebSocket 连接(login 实时画面代理), 返回连接信息。"""


class FakeKubeClient(KubeClient):
    """内存 fake, 供测试与本地运行。"""

    def __init__(self) -> None:
        self.pods: dict[str, PodStatus] = {}
        self.jobs: list[dict] = []
        self.deployments: dict[str, dict] = {}
        self.services: set[str] = set()
        self.created: list[CreateResult] = []
        self.deleted: list[tuple[str, str]] = []

    async def create_dev_pod(self, pod_spec: dict, service_spec: dict | None = None) -> CreateResult:
        name = pod_spec["metadata"]["name"]
        ns = pod_spec["metadata"]["namespace"]
        self.pods[name] = PodStatus(name=name, phase="Running", ready=True)
        self.created.append(CreateResult(pod_name=name))
        if service_spec is not None:
            self.services.add(service_spec["metadata"]["name"])
        return CreateResult(pod_name=name)

    async def get_pod_status(self, name: str, namespace: str) -> PodStatus:
        pod = self.pods.get(name)
        if pod is None:
            return PodStatus(name=name, phase="Unknown", ready=False, reason="not_found")
        return pod

    async def delete_pod(self, name: str, namespace: str) -> None:
        self.pods.pop(name, None)
        self.deleted.append((name, "pod"))

    async def delete_service(self, name: str, namespace: str) -> None:
        self.services.discard(name)
        self.deleted.append((name, "service"))

    async def create_run_job(self, job_spec: dict) -> None:
        self.jobs.append(job_spec)

    async def create_run_deployment(self, deploy_spec: dict) -> None:
        name = deploy_spec["metadata"]["name"]
        self.deployments[name] = deploy_spec

    async def delete_deployment(self, name: str, namespace: str) -> None:
        self.deployments.pop(name, None)
        self.deleted.append((name, "deployment"))

    async def proxy_ws(self, pod_name: str, namespace: str, path: str, port: int) -> dict:
        return {"pod": pod_name, "path": path, "port": port, "namespace": namespace}


class RealKubeClient(KubeClient):
    """生产实现(需要 kubernetes 依赖)。示例骨架, 按集群配置完善。"""

    def __init__(self, namespace: str = "cdc") -> None:
        self.namespace = namespace
        try:
            from kubernetes import client, config  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("缺少 kubernetes 依赖: pip install -e '.[kubernetes]'") from exc
        self._client = None

    def _api(self):
        if self._client is None:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except Exception:  # noqa: BLE001
                config.load_kube_config()
            self._client = client.CoreV1Api()
        return self._client

    async def create_dev_pod(self, pod_spec: dict, service_spec: dict | None = None) -> CreateResult:
        api = self._api()
        api.create_namespaced_pod(self.namespace, pod_spec)
        if service_spec is not None:
            api.create_namespaced_service(self.namespace, service_spec)
        return CreateResult(
            pod_name=pod_spec["metadata"]["name"],
            service_name=service_spec["metadata"]["name"] if service_spec else None,
        )

    async def get_pod_status(self, name: str, namespace: str) -> PodStatus:
        api = self._api()
        pod = api.read_namespaced_pod(name, namespace)
        phase = pod.status.phase or "Unknown"
        ready = bool(pod.status.container_statuses and all(c.ready for c in pod.status.container_statuses))
        reason = None
        if pod.status.container_statuses:
            waiting = pod.status.container_statuses[0].state.waiting
            reason = waiting.reason if waiting else None
        return PodStatus(name=name, phase=phase, ready=ready, reason=reason)

    async def delete_pod(self, name: str, namespace: str) -> None:
        self._api().delete_namespaced_pod(name, namespace)

    async def delete_service(self, name: str, namespace: str) -> None:
        self._api().delete_namespaced_service(name, namespace)

    async def create_run_job(self, job_spec: dict) -> None:
        from kubernetes import client

        client.BatchV1Api().create_namespaced_job(self.namespace, job_spec)

    async def create_run_deployment(self, deploy_spec: dict) -> None:
        from kubernetes import client

        client.AppsV1Api().create_namespaced_deployment(self.namespace, deploy_spec)

    async def delete_deployment(self, name: str, namespace: str) -> None:
        from kubernetes import client

        client.AppsV1Api().delete_namespaced_deployment(name, self.namespace)

    async def proxy_ws(self, pod_name: str, namespace: str, path: str, port: int) -> dict:
        # 生产: 使用 K8s port-forward(streaming) 或反向代理到 ClusterIP Service。
        # 本骨架返回连接参数, 由 HTTP 层做 port-forward 桥接。
        return {"pod": pod_name, "path": path, "port": port, "namespace": namespace}


def build_kube_client(namespace: str | None = None) -> KubeClient:
    """构造 KubeClient: 优先真实集群; 开发/本地环境回退 Fake(避免无集群时报错)。

    生产(非 dev/local)缺少 kubernetes 依赖时直接抛出, 防止"假成功"。
    """
    from ..config import settings

    try:
        return RealKubeClient(namespace or settings.k8s_namespace)
    except Exception:  # noqa: BLE001
        if settings.environment in ("dev", "local"):
            return FakeKubeClient()
        raise