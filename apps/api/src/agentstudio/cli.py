"""Operator command line.

agentstudio migrate
agentstudio user create --email you@example.com --name "You" --admin
agentstudio demo seed
agentstudio openapi --out docs/api/openapi.json
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from agentstudio.core.config import get_settings
from agentstudio.core.logging import configure_logging

app = typer.Typer(
    no_args_is_help=True, help="Euron AgentStudio command line.", add_completion=False
)
user_app = typer.Typer(no_args_is_help=True, help="Manage accounts.")
demo_app = typer.Typer(no_args_is_help=True, help="Demo data for local stacks.")
app.add_typer(user_app, name="user")
app.add_typer(demo_app, name="demo")


@app.callback()
def _setup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, "console")


@app.command()
def migrate() -> None:
    """Apply pending database migrations."""
    from agentstudio.db.migrate import migrate as run

    asyncio.run(run(get_settings()))
    typer.echo("migrations applied")


@user_app.command("create")
def create_user(
    email: Annotated[str, typer.Option(help="Sign-in email.")],
    name: Annotated[str, typer.Option(help="Display name.")],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
    admin: Annotated[bool, typer.Option(help="Instance administrator.")] = False,
) -> None:
    """Create an account."""
    from agentstudio.db.session import Database
    from agentstudio.services.users import create_user as create

    async def run() -> None:
        db = Database(get_settings())
        try:
            async with db.session() as session:
                user = await create(
                    session, email=email, name=name, password=password, is_admin=admin
                )
                typer.echo(f"created {user.email} ({user.id})")
        finally:
            await db.dispose()

    asyncio.run(run())


@demo_app.command("seed")
def seed(
    password: Annotated[
        str | None, typer.Option(envvar="DEMO_PASSWORD", help="Password for every demo account.")
    ] = None,
) -> None:
    """Demo accounts, a workspace with every template, knowledge bases and real runs."""
    from agentstudio.demo.seed import run

    settings = get_settings()
    if settings.is_production:
        raise typer.BadParameter("refusing to seed demo data with APP_ENV=production")
    secret = password or (
        settings.demo_password.get_secret_value() if settings.demo_password else None
    )
    if not secret:
        raise typer.BadParameter("set DEMO_PASSWORD (make env generates one)")
    asyncio.run(run(settings, secret))


@app.command()
def openapi(
    out: Annotated[Path, typer.Option(help="Where to write the OpenAPI document.")] = Path(
        "openapi.json"
    ),
) -> None:
    """Export the OpenAPI document generated from the routes."""
    from agentstudio.main import create_app

    schema = create_app().openapi()
    out.write_text(json.dumps(schema, indent=2, sort_keys=False) + "\n")
    typer.echo(f"wrote {out}")


if __name__ == "__main__":
    app()
