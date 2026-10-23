from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page[ItemT](ApiModel):
    items: list[ItemT]
    total: int
    limit: int
    offset: int


Limit = Annotated[int, Query(ge=1, le=100, description="Page size.")]
Offset = Annotated[int, Query(ge=0, description="Items to skip.")]
