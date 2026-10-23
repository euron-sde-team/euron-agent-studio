"""Exported scripts compile, run against the offline provider, and match the engine exactly."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from agentstudio.core.config import Settings
from agentstudio.engine.executor import Decision, Executor, Limits, RestoredStep, ResumeState
from agentstudio.engine.graph import GraphDocument
from agentstudio.engine.plan import Plan, build_plan
from agentstudio.engine.ports import EngineServices
from agentstudio.engine.recorder import MemoryRecorder
from agentstudio.export.python import ExportInfo, export_python, file_name
from agentstudio.integrations.http import GuardedHttpClient, NetworkPolicy
from agentstudio.integrations.sandbox import create_sandbox_app
from agentstudio.providers.offline import respond
from agentstudio.providers.offline.openai_api import ChatCompletionRequest, to_openai
from agentstudio.providers.registry import ModelRegistry
from agentstudio.templates import TEMPLATES, bind_knowledge, get_template, knowledge_names
from tests.unit.helpers import FakeCancel, MemoryKnowledge, edge, graph, node

STUDIO = "http://studio.test"


def studio_app(knowledge: MemoryKnowledge) -> FastAPI:
    """What an exported script talks to: the offline model, the sandbox, knowledge search."""
    app = FastAPI()

    @app.post("/api/v1/offline/v1/chat/completions")
    async def completions(body: ChatCompletionRequest) -> dict[str, Any]:
        return to_openai(body, respond(body.to_request()))

    @app.post("/api/v1/workspaces/{workspace}/knowledge-bases/{kb_id}/search")
    async def search(workspace: str, kb_id: uuid.UUID, body: dict[str, Any]) -> dict[str, Any]:
        results = await knowledge.search(kb_id, body["query"], body["top_k"])
        return {"results": results, "context": ""}

    app.mount("/sandbox", create_sandbox_app())
    return app


def load(source: str, tmp_path: Path, name: str) -> ModuleType:
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


async def engine_outputs(
    plan: Plan, inputs: dict[str, Any], knowledge: MemoryKnowledge
) -> dict[str, Any]:
    """Run the plan in the engine, approving any approval step, and return the outputs."""
    http = GuardedHttpClient(NetworkPolicy(), sandbox=create_sandbox_app())
    services = EngineServices(
        models=ModelRegistry(Settings(), None), knowledge=knowledge, http=http, cancel=FakeCancel()
    )
    resume = ResumeState()
    try:
        for _ in range(5):
            recorder = MemoryRecorder()
            result = await Executor(
                plan, services, recorder, limits=Limits(cancel_poll_s=0.05)
            ).execute(inputs, resume)
            if result.status != "waiting":
                assert result.status == "succeeded", result.error
                return result.outputs
            for step in recorder.finished:
                if step.iteration == "" and step.status in ("succeeded", "skipped"):
                    resume.steps[step.node_id] = RestoredStep(
                        step.status, step.output, step.handles
                    )
            for waiting in result.waiting_on:
                resume.decisions[waiting] = Decision(approved=True)
        raise AssertionError("the run never finished")
    finally:
        await http.aclose()


def template_plan(slug: str, knowledge: MemoryKnowledge) -> tuple[Plan, Any]:
    template = get_template(slug)
    assert template is not None
    ids = {name: knowledge.load(name) for name in knowledge_names(template.graph)}
    plan = build_plan(GraphDocument.model_validate(bind_knowledge(template.graph, ids)))
    return plan, template


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.slug)
async def test_exported_templates_reproduce_the_engine(template: Any, tmp_path: Path) -> None:
    knowledge = MemoryKnowledge()
    plan, _ = template_plan(template.slug, knowledge)
    source = export_python(plan, ExportInfo(template.name, "northwind", "v1", STUDIO))
    compile(source, file_name(template.name), "exec")
    module = load(source, tmp_path, f"exported_{template.slug.replace('-', '_')}")
    module.APPROVAL_MODE = "approve"
    transport = httpx.ASGITransport(app=studio_app(knowledge))
    async with httpx.AsyncClient(transport=transport) as client:
        script_outputs = await module.run_flow(template.sample, client)
    expected = await engine_outputs(plan, template.sample, knowledge)
    assert script_outputs == expected
    assert script_outputs


def test_scripts_are_readable_and_self_describing() -> None:
    knowledge = MemoryKnowledge()
    plan, template = template_plan("support-triage", knowledge)
    source = export_python(plan, ExportInfo(template.name, "northwind", "v3", STUDIO))
    assert source.startswith("#!/usr/bin/env python3\n")
    assert "pip install httpx jmespath" in source
    assert "def run_flow(" in source
    assert "# 2. Classify ticket (Prompt)" in source
    assert "NODE_CLASSIFY = {" in source
    assert "FLOW_VERSION = 'v3'" in source
    assert "if run.reached(('classify', 'out')):" in source
    assert file_name("Support ticket triage!") == "support_ticket_triage.py"
    research, info = template_plan("research-brief", knowledge)
    looped = export_python(research, ExportInfo(info.name, "northwind", "v1", STUDIO))
    assert "# 3.1 Search the library (Knowledge search)" in looped
    assert "body = run.child('each_question', item, index)" in looped
    assert all(
        len(line) <= 120 for line in source.splitlines() if not line.lstrip().startswith(("'", '"'))
    )


HOSTILE = '"""\'\'\'\nimport os; os.system("echo pwned")  # \\ {{inputs.text}}\r\n\x00'


def test_hostile_strings_stay_data(tmp_path: Path) -> None:
    flow = graph(
        [
            node("start", "start", x=0, inputs=[{"name": "text"}], label=HOSTILE),
            node(
                "echo",
                "output",
                x=10,
                label=HOSTILE,
                fields=[
                    {"name": "said", "value": "{{inputs.text}}"},
                    {"name": "fixed", "value": HOSTILE},
                ],
            ),
        ],
        [edge("start", "echo")],
    )
    source = export_python(build_plan(flow), ExportInfo(HOSTILE, HOSTILE, HOSTILE, STUDIO))
    tree = ast.parse(source)
    calls = {
        sub.func.attr
        for sub in ast.walk(tree)
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
    }
    assert "system" not in calls
    module = load(source, tmp_path, "exported_hostile")
    outputs = asyncio.run(module.run_flow({"text": HOSTILE}, httpx.AsyncClient()))
    assert outputs == {"said": HOSTILE, "fixed": HOSTILE.replace("{{inputs.text}}", HOSTILE)}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_exported_scripts_run_as_programs(tmp_path: Path) -> None:
    """The real thing: a subprocess, its own event loop, plain HTTP to the offline model."""
    knowledge = MemoryKnowledge()
    plan, template = template_plan("invoice-extraction", knowledge)
    script = tmp_path / file_name(template.name)
    script.write_text(export_python(plan, ExportInfo(template.name, "northwind", "v1", STUDIO)))
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(studio_app(knowledge), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        env = {**os.environ, "AGENTSTUDIO_URL": f"http://127.0.0.1:{port}"}
        done = subprocess.run(  # noqa: S603 (our own interpreter running a script we just wrote)
            [sys.executable, str(script), "--approve"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert done.returncode == 0, done.stderr
    outputs = json.loads(done.stdout)
    assert outputs["status"] == "posted"
    assert outputs["record"]["invoice_number"] == "AOS-2026-0417"
