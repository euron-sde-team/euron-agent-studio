"""The template gallery and the models this deployment offers."""

from __future__ import annotations

from fastapi import APIRouter

from agentstudio.api import presenters
from agentstudio.api.deps import ContainerDep, PrincipalDep
from agentstudio.schemas.catalog import ModelOut, TemplateOut
from agentstudio.services.templates import TemplateService

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/templates", summary="Ready-made flows")
async def list_templates(principal: PrincipalDep) -> list[TemplateOut]:
    return [presenters.template_out(t) for t in TemplateService.all()]


@router.get("/templates/{slug}", summary="One template with its graph")
async def get_template(slug: str, principal: PrincipalDep) -> TemplateOut:
    return presenters.template_out(TemplateService.get(slug))


@router.get("/models", summary="Configured model providers and models")
async def list_models(principal: PrincipalDep, container: ContainerDep) -> list[ModelOut]:
    return [presenters.model_out(info) for info in container.models.models()]
