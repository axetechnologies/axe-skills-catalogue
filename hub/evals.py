"""EvalStore interface and no-op stub for the public catalogue.

The full eval pipeline is not part of the public surface. `NoOpEvalStore`
satisfies the interface that serve.py expects so the server starts without
a private eval database. The /healthz endpoint exposes whether a real
EvalStore is in use via the `"evals"` field, so consumers can distinguish
"this skill has no eval" from "this deployment does not serve evals at all".
"""
from __future__ import annotations

from pathlib import Path


class EvalStore:
    """Base interface. Subclass or replace with a real implementation."""

    def __init__(self, db_path: Path | None = None) -> None:
        pass

    def latest(self, tenant_id: str, name: str, version: str) -> dict | None:
        raise NotImplementedError


class NoOpEvalStore(EvalStore):
    """Stub for deployments that do not serve eval results."""

    def latest(self, tenant_id: str, name: str, version: str) -> None:
        return None


# Re-export so callers that import EvalStore from hub.evals get the stub
# automatically. A deployment with real evals replaces this at make_server()
# call time by passing its own EvalStore subclass.
_NoOpEvalStore = NoOpEvalStore
