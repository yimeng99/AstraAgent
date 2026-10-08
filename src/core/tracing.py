"""OTel 初始化、日志关联与少量业务埋点；模型调用树由框架插桩维护。"""

from __future__ import annotations

import json
import os
import re
from base64 import b64encode
from contextlib import contextmanager, suppress
from contextvars import ContextVar

from openinference.instrumentation import TraceConfig
from openinference.instrumentation.langchain import LangChainInstrumentor, get_current_span
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from core.utils.logging import get_logger

logger = get_logger(__name__)
_provider: TracerProvider | None = None
_scope: ContextVar[dict | None] = ContextVar("tracing_scope", default=None)
_capture_content = False
_secrets: tuple[str, ...] = ()


def _safe_content(value):
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]"
            if re.search(
                r"token|password|secret|authorization|api.?key|context|config", str(k), re.I
            )
            or str(k) in {"image_url", "files"}
            else _safe_content(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_safe_content(v) for v in value[:100]]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                return _safe_content(json.loads(value))
            except ValueError:
                pass
        for secret in _secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", value, flags=re.I)
        return value[:16000]
    return value


def capture_io(span, key: str, value) -> None:
    """只传业务输入输出，不传 runtime/config；上限避免附件占满追踪存储。"""
    if _capture_content and span.is_recording():
        span.set_attribute(
            f"{key}.value",
            json.dumps(_safe_content(value), ensure_ascii=False, default=str)[:32000],
        )


class _IdentityProcessor(SpanProcessor):
    def on_start(self, span, parent_context=None):
        # Langfuse 按 observation 聚合会话；身份必须随子节点传播，不能只写根节点。
        if identity := _scope.get():
            span.set_attributes(identity)


# 白名单出口：框架可能把整个运行时上下文塞进 metadata，不能只隐藏 prompt。
_SAFE_ATTRIBUTES = {
    "openinference.span.kind",
    "llm.model_name",
    "llm.provider",
    "llm.system",
    "llm.token_count.prompt",
    "llm.token_count.completion",
    "llm.token_count.total",
    "llm.token_count.prompt_details.cache_read",
    "llm.token_count.prompt_details.cache_write",
    "llm.token_count.completion_details.reasoning",
    "tool.name",
    "http.method",
    "http.status_code",
    "http.route",
    "http.request.method",
    "http.response.status_code",
    "server.address",
    "server.port",
    "request_id",
    "thread_id",
    "user_id",
    "tenant_id",
    "project_id",
    "run_id",
    "agent.resume",
    "agent.state",
    "agent.first_token_ms",
    "sandbox.exit_code",
    "error.type",
    "db.system",
    "db.operation",
}


class _SafeExporter(OTLPSpanExporter):
    def export(self, spans):
        safe = []
        for span in spans:
            attributes = {k: v for k, v in (span.attributes or {}).items() if k in _SAFE_ATTRIBUTES}
            # 平台只接收会话执行中的节点，启动及文件面板轮询不形成孤立记录。
            if not attributes.get("thread_id"):
                continue
            if attributes.get("user_id"):
                attributes["langfuse.user.id"] = attributes["user_id"]
            if attributes.get("thread_id"):
                attributes["langfuse.session.id"] = attributes["thread_id"]
            kind = str(attributes.get("openinference.span.kind", "")).upper()
            if _capture_content and (
                kind in {"LLM", "TOOL"} or span.name in {"agent.execute", "astra-agent"}
            ):
                for key in ("input.value", "output.value"):
                    value = (span.attributes or {}).get(key)
                    if value is not None:
                        with suppress(ValueError, TypeError):
                            value = json.loads(value)
                        value = _safe_content(value)
                        attributes[key] = (
                            value
                            if isinstance(value, str)
                            else json.dumps(value, ensure_ascii=False)
                        )[:32000]
            attributes["langfuse.trace.name"] = "Agent 对话"
            attributes["langfuse.observation.type"] = (
                "agent"
                if span.name == "agent.execute"
                else {
                    "LLM": "generation",
                    "TOOL": "tool",
                    "AGENT": "agent",
                    "CHAIN": "chain",
                    "RETRIEVER": "retriever",
                    "EMBEDDING": "embedding",
                }.get(kind, "span")
            )
            for key in (
                "tenant_id",
                "project_id",
                "run_id",
                "agent.state",
                "agent.resume",
                "agent.first_token_ms",
                "sandbox.exit_code",
                "error.type",
            ):
                if key in attributes:
                    attributes[f"langfuse.observation.metadata.{key.replace('.', '_')}"] = (
                        attributes[key]
                    )
            safe.append(
                ReadableSpan(
                    name=span.name,
                    context=span.context,
                    parent=span.parent,
                    resource=span.resource,
                    kind=span.kind,
                    attributes=attributes,
                    events=[
                        Event(
                            e.name,
                            attributes={
                                k: v for k, v in e.attributes.items() if k == "exception.type"
                            },
                            timestamp=e.timestamp,
                        )
                        for e in span.events
                    ],
                    links=span.links,
                    status=trace.Status(span.status.status_code),
                    start_time=span.start_time,
                    end_time=span.end_time,
                    instrumentation_scope=span.instrumentation_scope,
                )
            )
        if safe:
            return super().export(safe)
        from opentelemetry.sdk.trace.export import SpanExportResult

        return SpanExportResult.SUCCESS


def init_tracing(config) -> None:
    """每个服务进程初始化一次；后台批量上报，不阻塞请求等待追踪平台。"""
    global _provider, _capture_content, _secrets
    if not config.enabled or _provider is not None:
        return
    _capture_content = config.capture_content
    _secrets = tuple(
        v
        for k, v in os.environ.items()
        if len(v) >= 8 and re.search(r"TOKEN|PASSWORD|SECRET|API_KEY", k, re.I)
    )
    provider = TracerProvider(
        resource=Resource.create({"service.name": "astra-agent", "service.version": "0.1.0"}),
        sampler=ParentBased(TraceIdRatioBased(config.sample_rate)),
    )
    credentials = b64encode(
        f"{config.public_key}:{config.secret_key.get_secret_value()}".encode()
    ).decode()
    provider.add_span_processor(_IdentityProcessor())
    provider.add_span_processor(
        BatchSpanProcessor(
            _SafeExporter(
                endpoint=config.endpoint,
                timeout=3,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "x-langfuse-ingestion-version": "4",
                },
            ),
            max_queue_size=2048,
        )
    )
    trace.set_tracer_provider(provider)
    LangChainInstrumentor().instrument(
        tracer_provider=provider,
        config=TraceConfig(
            hide_inputs=not config.capture_content,
            hide_outputs=not config.capture_content,
            hide_llm_invocation_parameters=True,
            hide_embedding_vectors=True,
        ),
    )
    _provider = provider
    logger.info("tracing.started", service="astra-agent")


def shutdown_tracing() -> None:
    """退出时提交队列；Provider 生命周期与进程一致。"""
    if _provider is not None:
        _provider.shutdown()


def trace_fields() -> dict[str, str]:
    span = get_current_span() or trace.get_current_span()
    ctx = span.get_span_context()
    return (
        {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")}
        if ctx.is_valid
        else {}
    )


@contextmanager
def operation(name: str, **attributes):
    """沙箱操作可能在工具线程内，显式接到对应 LangChain 工具 Span。"""
    parent = get_current_span()
    context = trace.set_span_in_context(parent) if parent is not None else None
    token = None
    if name == "agent.execute":
        identity = {
            k: attributes[k]
            for k in ("user_id", "thread_id", "tenant_id", "project_id", "run_id")
            if k in attributes
        }
        token = _scope.set(identity)
        trace.get_current_span().set_attributes(identity)
    try:
        with trace.get_tracer(__name__).start_as_current_span(
            name,
            context=context,
            attributes=attributes,
        ) as span:
            try:
                yield span
            except BaseException as exc:
                if name == "agent.execute":
                    span.set_attribute(
                        "agent.state", "failed" if isinstance(exc, Exception) else "cancelled"
                    )
                raise
    finally:
        if token is not None:
            _scope.reset(token)
