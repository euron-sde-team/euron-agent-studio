"""The sandbox API: deterministic fixture endpoints that let template flows run offline.

Flows reach it at https://sandbox.agentstudio.test (a reserved name that never resolves on
the internet; the engine answers it in process), and exported scripts reach the same app at
`<AgentStudio URL>/sandbox`. Responses depend only on the request, never on time or state,
so a flow run and its exported script see identical data.
"""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agentstudio.integrations.sandbox import data


def _not_found(message: str) -> JSONResponse:
    return JSONResponse({"error": "not_found", "message": message}, status_code=404)


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def _normalise_vendor(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    cleaned = re.sub(r"\b(ltd|limited|inc|llc|co|corp|corporation|plc|gmbh)\b", " ", cleaned)
    return " ".join(cleaned.split())


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    assignee: str | None = Field(default=None, max_length=120)
    due: str | None = Field(default=None, max_length=60)
    source: str | None = Field(default=None, max_length=200)


def create_sandbox_app() -> FastAPI:
    app = FastAPI(
        title="AgentStudio sandbox",
        description="Fictional CRM, ERP, task and exchange-rate endpoints for offline flows.",
        version="1",
        docs_url="/docs",
        redoc_url=None,
    )

    @app.get("/")
    async def index() -> dict[str, Any]:
        return {
            "service": "AgentStudio sandbox",
            "endpoints": [
                "GET /crm/contacts?email=",
                "GET /crm/companies/lookup?domain= or ?email=",
                "GET /erp/vendors?name=",
                "POST /tasks",
                "GET /fx/rates?base=",
            ],
        }

    @app.get("/crm/contacts", response_model=None)
    async def contact(
        email: Annotated[str, Query(max_length=200)],
    ) -> dict[str, Any] | JSONResponse:
        found = data.CONTACTS.get(email.strip().lower())
        if found is None:
            return _not_found("No contact with that email address.")
        return {"email": email.strip().lower(), **found}

    @app.get("/crm/companies/lookup", response_model=None)
    async def company(
        domain: Annotated[str | None, Query(max_length=200)] = None,
        email: Annotated[str | None, Query(max_length=200)] = None,
    ) -> dict[str, Any] | JSONResponse:
        name = (
            (domain or (email.split("@", 1)[1] if email and "@" in email else "")).strip().lower()
        )
        if not name:
            return JSONResponse(
                {"error": "bad_request", "message": "Pass a domain or an email."}, status_code=400
            )
        if name in data.PERSONAL_DOMAINS:
            return _not_found("That is a personal email domain, not a company.")
        known = data.COMPANIES.get(name)
        if known is not None:
            return {"domain": name, **known, "source": "crm"}
        # Unknown domains get a stable, clearly synthetic profile so any input still works.
        seed = _seed(name)
        label = name.split(".")[0].replace("-", " ").title()
        return {
            "domain": name,
            "name": label,
            "industry": data.INDUSTRIES[seed % len(data.INDUSTRIES)],
            "employees": 20 + seed % 1980,
            "annual_revenue_usd": (2 + seed % 300) * 1_000_000,
            "region": data.REGIONS[seed % len(data.REGIONS)],
            "existing_customer": False,
            "tech_stack": [],
            "source": "synthetic",
        }

    @app.get("/erp/vendors", response_model=None)
    async def vendor(name: Annotated[str, Query(max_length=200)]) -> dict[str, Any] | JSONResponse:
        found = data.VENDORS.get(_normalise_vendor(name))
        if found is None:
            return _not_found("No vendor with that name in the ERP.")
        return found

    @app.post("/tasks", status_code=201)
    async def create_task(task: TaskIn) -> dict[str, Any]:
        number = 1000 + _seed(f"{task.title}|{task.assignee}") % 9000
        identifier = f"TSK-{number}"
        return {
            "id": identifier,
            "title": task.title,
            "assignee": task.assignee,
            "due": task.due,
            "status": "open",
            "url": f"https://tasks.sandbox.agentstudio.test/{identifier}",
        }

    @app.get("/fx/rates", response_model=None)
    async def rates(
        base: Annotated[str, Query(max_length=3)] = "USD",
    ) -> dict[str, Any] | JSONResponse:
        table = data.FX_RATES.get(base.upper())
        if table is None:
            return _not_found(f"No rates for {base.upper()}.")
        return {"base": base.upper(), "rates": table, "as_of": data.FX_AS_OF}

    return app
