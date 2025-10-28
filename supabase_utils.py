from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

try:
    import streamlit as st
except ImportError:  # pragma: no cover - streamlit not available during some tests
    st = None

from supabase import Client, create_client


DEFAULT_SUPABASE_BUCKET = "ticket-csvs"
DEFAULT_METADATA_OBJECT = "_dataset_registry.json"


@dataclass
class DatasetMeta:
    """Represents metadata stored for a dataset object."""

    name: str
    included: bool = True
    disabled: bool = False
    uploaded_at: Optional[str] = None

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "DatasetMeta":
        return cls(
            name=name,
            included=bool(data.get("included", True)),
            disabled=bool(data.get("disabled", False)),
            uploaded_at=data.get("uploaded_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "included": self.included,
            "disabled": self.disabled,
        }
        if self.uploaded_at:
            payload["uploaded_at"] = self.uploaded_at
        return payload


class SupabaseConfigError(RuntimeError):
    """Raised when Supabase configuration is missing or invalid."""


def _supabase_secrets() -> Dict[str, Any]:
    if st is None:
        return {}
    try:
        return dict(st.secrets.get("supabase", {}))
    except Exception:
        return {}


def _config_value(env_key: str, secret_key: str, default: Optional[str] = None) -> str:
    secrets = _supabase_secrets()
    if secret_key in secrets and secrets[secret_key]:
        return str(secrets[secret_key])

    value = os.getenv(env_key)
    if value:
        return value

    if default is not None:
        return default

    raise SupabaseConfigError(
        f"Supabase configuration missing. Set environment variable {env_key} or add '{secret_key}' to st.secrets['supabase']."
    )


def _is_disabled() -> bool:
    secrets = _supabase_secrets()
    secret_value = secrets.get("disable")
    if isinstance(secret_value, bool):
        disable_flag = secret_value
    elif isinstance(secret_value, str):
        disable_flag = secret_value.lower() in {"1", "true", "yes"}
    else:
        disable_flag = False

    if disable_flag:
        return True

    env_value = os.getenv("SUPABASE_DISABLE")
    if env_value is None:
        return False
    return env_value.lower() in {"1", "true", "yes"}


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Initialise and cache the Supabase client."""

    url = _config_value("SUPABASE_URL", "url")
    key = _config_value("SUPABASE_ANON_KEY", "anon_key")
    try:
        return create_client(url, key)
    except Exception as exc:
        raise SupabaseConfigError("Unable to initialise Supabase client") from exc


def get_bucket_name() -> str:
    return _config_value("SUPABASE_BUCKET", "bucket", DEFAULT_SUPABASE_BUCKET)


def get_metadata_path() -> str:
    return _config_value(
        "SUPABASE_METADATA_OBJECT", "metadata_object", DEFAULT_METADATA_OBJECT
    )


def list_csv_objects() -> List[Dict[str, Any]]:
    """List CSV objects stored within the configured bucket."""

    client = get_client()
    bucket = get_bucket_name()
    try:
        response = client.storage.from_(bucket).list()
    except Exception as exc:
        raise RuntimeError("Failed to list Supabase storage objects") from exc

    # Supabase returns list of dicts with keys like name, created_at etc.
    return [item for item in response if item.get("name", "").lower().endswith(".csv")]


def download_csv(name: str) -> bytes:
    client = get_client()
    bucket = get_bucket_name()
    try:
        response = client.storage.from_(bucket).download(name)
    except Exception as exc:
        raise RuntimeError(f"Failed to download {name} from Supabase storage") from exc
    return response  # Supabase returns raw bytes


def load_metadata() -> Dict[str, DatasetMeta]:
    """Retrieve dataset metadata stored as JSON. Returns empty mapping by default."""

    client = get_client()
    bucket = get_bucket_name()
    path = get_metadata_path()
    try:
        response = client.storage.from_(bucket).download(path)
    except Exception:
        # Missing metadata (404) or any other failure should fall back to empty state.
        return {}

    try:
        raw = json.loads(response.decode("utf-8"))
    except Exception:
        # Corrupt metadata should not break the app; start fresh.
        return {}

    datasets = raw.get("datasets", {})
    return {
        name: DatasetMeta.from_dict(name, value) for name, value in datasets.items()
    }


def save_metadata(metadata: Dict[str, DatasetMeta]) -> None:
    client = get_client()
    bucket = get_bucket_name()
    path = get_metadata_path()
    payload = {
        "datasets": {name: meta.to_dict() for name, meta in metadata.items()}
    }
    data = json.dumps(payload, indent=2).encode("utf-8")
    options = {"content-type": "application/json", "upsert": "true"}
    try:
        client.storage.from_(bucket).upload(path, data, options)
    except Exception as exc:
        raise RuntimeError("Failed to persist dataset metadata to Supabase storage") from exc


def upload_csv(name: str, data: bytes) -> None:
    client = get_client()
    bucket = get_bucket_name()
    try:
        client.storage.from_(bucket).upload(
            name,
            data,
            {"contentType": "text/csv"},
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to upload {name} to Supabase storage") from exc


def delete_object(name: str) -> None:
    client = get_client()
    bucket = get_bucket_name()
    try:
        client.storage.from_(bucket).remove([name])
    except Exception as exc:
        raise RuntimeError(f"Failed to delete {name} from Supabase storage") from exc


def supabase_disabled() -> bool:
    return _is_disabled()
