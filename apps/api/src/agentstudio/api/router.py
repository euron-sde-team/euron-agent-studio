from __future__ import annotations

from fastapi import APIRouter

from agentstudio.api.routes import (
    api_keys,
    approvals,
    auth,
    catalog,
    dashboard,
    flows,
    health,
    hooks,
    knowledge,
    offline,
    runs,
    secrets,
    workspaces,
)

api_router = APIRouter()
for module in (
    health,
    auth,
    workspaces,
    dashboard,
    flows,
    runs,
    approvals,
    knowledge,
    secrets,
    api_keys,
    catalog,
    offline,
    hooks,
):
    api_router.include_router(module.router)
