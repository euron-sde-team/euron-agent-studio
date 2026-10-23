"""Errors raised while a node runs.

A `NodeError` carries a stable code (shown in traces and used by retries), a message for
people, and whether trying again could help.
"""

from __future__ import annotations

from typing import Any

# HTTP statuses worth retrying: the request may succeed if sent again later.
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class NodeError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            data["details"] = self.details
        return data


class RunFailedError(Exception):
    """A node failed without `continue_on_error`; the whole run fails."""

    def __init__(self, node_id: str, error: NodeError) -> None:
        super().__init__(f"{node_id}: {error.message}")
        self.node_id = node_id
        self.error = error
