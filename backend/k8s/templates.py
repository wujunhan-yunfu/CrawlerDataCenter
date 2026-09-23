"""K8s 编排模板: Pod / Service / Ingress 规格构造。

生产使用真实 kubernetes 客户端(可装 optional kubernetes 依赖);
测试注入 FakeKubeClient(services/dev_container.py)。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DevPodSpec:
    crawler_id: str
    namespace: str
    image: str
    mongo_uri: str
    mongo_db: str = "crawler"
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    llm_secret_ref: str = "llm-api-key"
    web_port: int = 8080
    api_prefix: str = "/api/v1"
    cpu_limit: str = "2"
    mem_limit: str = "2Gi"
    cpu_request: str = "500m"
    mem_request: str = "512Mi"
    labels: dict = field(default_factory=dict)


def pod_name_for(crawler_id: str, role: str = "dev") -> str:
    safe = "".join(c if c.isalnum() else "-" for c in crawler_id)[:40].strip("-")
    return f"acs-{role}-{safe}"


def service_name_for(crawler_id: str) -> str:
    return pod_name_for(crawler_id)


def build_dev_pod(spec: DevPodSpec) -> dict:
    name = pod_name_for(spec.crawler_id)
    labels = {"app": "acs", "role": "dev", "crawler-id": spec.crawler_id, **spec.labels}
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": spec.namespace, "labels": labels},
        "spec": {
            "containers": [
                {
                    "name": "acs",
                    "image": spec.image,
                    "env": [
                        {"name": "MODE", "value": "dev"},
                        {"name": "CRAWLER_ID", "value": spec.crawler_id},
                        {"name": "MONGO_URI", "value": spec.mongo_uri},
                        {"name": "MONGO_DB", "value": spec.mongo_db},
                        {"name": "LLM_PROVIDER", "value": spec.llm_provider},
                        {"name": "LLM_MODEL", "value": spec.llm_model},
                        {"name": "LLM_API_KEY", "valueFrom": {"secretKeyRef": {"name": spec.llm_secret_ref, "key": "value"}}},
                        {"name": "WEB_PORT", "value": str(spec.web_port)},
                        {"name": "API_PREFIX", "value": spec.api_prefix},
                    ],
                    "resources": {
                        "limits": {"cpu": spec.cpu_limit, "memory": spec.mem_limit},
                        "requests": {"cpu": spec.cpu_request, "memory": spec.mem_request},
                    },
                    "readinessProbe": {
                        "httpGet": {"path": "/healthz", "port": spec.web_port},
                        "initialDelaySeconds": 5,
                        "periodSeconds": 3,
                    },
                    "securityContext": {"runAsNonRoot": True, "readOnlyRootFilesystem": True},
                }
            ],
            "restartPolicy": "Never",
        },
    }


def build_dev_service(crawler_id: str, namespace: str, port: int = 8080) -> dict:
    name = service_name_for(crawler_id)
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": namespace, "labels": {"app": "acs", "role": "dev"}},
        "spec": {
            "selector": {"app": "acs", "role": "dev", "crawler-id": crawler_id},
            "ports": [{"name": "http", "port": 8080, "targetPort": port}],
            "type": "ClusterIP",
        },
    }


def build_run_job(crawler_id: str, namespace: str, env: dict, image: str) -> dict:
    """一次性 run Job 模板。"""
    name = pod_name_for(crawler_id, role="run")
    labels = {"app": "acs", "role": "run", "crawler-id": crawler_id}
    env_list = [{"name": k, "value": str(v)} for k, v in env.items()]
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [{"name": "acs-run", "image": image, "env": env_list}],
                },
            }
        },
    }


def build_run_deployment(crawler_id: str, namespace: str, env: dict, image: str) -> dict:
    """cron 常驻 run Deployment(replicas=1)。"""
    name = pod_name_for(crawler_id, role="run")
    labels = {"app": "acs", "role": "run", "crawler-id": crawler_id}
    env_list = [{"name": k, "value": str(v)} for k, v in env.items()]
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "containers": [{"name": "acs-run", "image": image, "env": env_list}],
                },
            },
        },
    }