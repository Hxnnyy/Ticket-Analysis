from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

from supabase import Client, create_client


DEFAULT_SUPABASE_URL = "https://lkffiqvyrjtqptvjoksb.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxrZmZpcXZ5cmp0cXB0dmpva3NiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE2MzE4NjUsImV4cCI6MjA3NzIwNzg2NX0.TVq7mhSJSGEuOw8A9x5UEyOGnnm8Y5S9PGnNEDbLhGE"
)
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


def _config_value(env_key: str, default: Optional[str]) -> str:
    value = os.getenv(env_key, default)
    if not value:
        raise SupabaseConfigError(
            f"Environment variable {env_key} is required for Supabase integration."
        )
    return value


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Initialise and cache the Supabase client."""

    url = _config_value("SUPABASE_URL", DEFAULT_SUPABASE_URL)
    key = _config_value("SUPABASE_ANON_KEY", DEFAULT_SUPABASE_ANON_KEY)
    try:
        return create_client(url, key)
    except Exception as exc:
        raise SupabaseConfigError("Unable to initialise Supabase client") from exc


def get_bucket_name() -> str:
    return _config_value("SUPABASE_BUCKET", DEFAULT_SUPABASE_BUCKET)


def get_metadata_path() -> str:
    return os.getenv("SUPABASE_METADATA_OBJECT", DEFAULT_METADATA_OBJECT)


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
    try:
        client.storage.from_(bucket).upload(
            path,
            data,
            {"contentType": "application/json", "upsert": True},
        )
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
