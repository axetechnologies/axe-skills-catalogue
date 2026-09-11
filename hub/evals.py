"""Minimal EvalStore stub for the public catalogue.

The full eval pipeline is not part of the public surface. This stub satisfies
the interface that serve.py expects so the server starts without the private
eval database.
"""
from __future__ import annotations

from pathlib import Path


class EvalStore:
    def __init__(self, db_path: Path | None = None) -> None:
        pass

    def latest(self, tenant_id: str, name: str, version: str) -> None:
        return None
