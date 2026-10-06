"""Fail-closed WSGI entry point for the hosted beta runtime."""

from __future__ import annotations

import os
from pathlib import Path

_DATA_ROOT = Path("/data").resolve()


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Hosted runtime requires {name} to be configured.")
    return value


def _persistent_data_path(name: str) -> Path:
    value = Path(_required(name))
    if not value.is_absolute():
        raise RuntimeError(f"Hosted runtime requires {name} to be an absolute /data path.")
    resolved = value.resolve()
    if not resolved.is_relative_to(_DATA_ROOT):
        raise RuntimeError(f"Hosted runtime requires {name} to remain under the mounted /data volume.")
    return resolved


if os.environ.get("ROUTE_SHARE_HOSTED", "").strip() != "1":
    raise RuntimeError("Set ROUTE_SHARE_HOSTED=1 to run the hosted WSGI entry point.")

if not _DATA_ROOT.is_dir():
    raise RuntimeError("The persistent /data volume must be mounted before the hosted app starts.")

database_path = _persistent_data_path("BETA_DATABASE")
secret_path = _persistent_data_path("BETA_SECRET_FILE")
if database_path == secret_path:
    raise RuntimeError("BETA_DATABASE and BETA_SECRET_FILE must point to separate files.")

_required("PUBLIC_ORIGIN")
_required("BETA_ACCOUNT_PASSWORDS")

from app import create_app  # noqa: E402  (validate hosted config before app initialization)

app = create_app()
