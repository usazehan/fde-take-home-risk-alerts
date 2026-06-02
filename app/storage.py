from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.fs as pafs

class StorageError(Exception):
    """Raised when a source_uri cannot be resolved or scanned."""

@dataclass(frozen=True)
class ParquetSource:
    uri: str
    scheme: str
    path: str
    filesystem: pafs.FileSystem

def open_uri(source_uri: str) -> ds.Dataset:
    """
    Open a source_uri as a lazy PyArrow parquet dataset.

    Supported:
      - file://... or bare local path
      - gs://bucket/path/file.parquet

    Recognized but not implemented:
      - s3://bucket/path/file.parquet

    """
    source = _resolve_source(source_uri)

    try:
        return ds.dataset(
            source.path,
            filesystem=source.filesystem,
            format="parquet",
        )
    except Exception as exc:
        raise StorageError(f"Failed to open Parquet source {source_uri}: {exc}") from exc


def read_table(
    source_uri: str,
    *,
    columns: list[str] | None = None,
    filter_expression: ds.Expression | None = None,
) -> pa.Table:
    """
    Scan a parquet source into an Arrow table using projection and filtering.

    This is the main entry point risk_logic.py should use.

    Example:
        read_table(
            source_uri,
            columns=["account_id", "month", "status", "updated_at"],
            filter_expression=ds.field("month") <= target_month,
        )
    """
    dataset = open_uri(source_uri)

    try:
        return dataset.to_table(
            columns=columns,
            filter=filter_expression,
        )
    except Exception as exc:
        raise StorageError(f"Failed to scan Parquet source {source_uri}: {exc}") from exc


def _resolve_source(source_uri: str) -> ParquetSource:
    parsed = urlparse(source_uri)
    scheme = parsed.scheme.lower()

    if scheme in ("", "file"):
        return _resolve_local_source(source_uri, parsed)

    if scheme == "gs":
        return _resolve_gcs_source(source_uri, parsed)

    raise StorageError(
        f"Unsupported source_uri scheme: {scheme!r}. "
        "Supported schemes are file://, gs://, or a bare local path."
    )


def _resolve_local_source(source_uri: str, parsed) -> ParquetSource:
    if parsed.scheme == "":
        file_path = Path(source_uri)
    else:
        # file:///tmp/data.parquet -> /tmp/data.parquet
        # file://localhost/tmp/data.parquet -> /tmp/data.parquet
        if parsed.netloc and parsed.netloc != "localhost":
            file_path = Path(unquote(parsed.netloc + parsed.path))
        else:
            file_path = Path(unquote(parsed.path))

    if not file_path.exists():
        raise StorageError(f"Local file not found: {file_path}")

    if not file_path.is_file():
        raise StorageError(f"Local path is not a file: {file_path}")

    return ParquetSource(
        uri=source_uri,
        scheme="file",
        path=str(file_path),
        filesystem=pafs.LocalFileSystem(),
    )

def _resolve_gcs_source(source_uri: str, parsed) -> ParquetSource:
    bucket_name = parsed.netloc
    object_path = parsed.path.lstrip("/")

    if not bucket_name:
        raise StorageError("GCS URI is missing bucket name.")

    if not object_path:
        raise StorageError("GCS URI is missing object path.")

    return ParquetSource(
        uri=source_uri,
        scheme="gs",
        path=f"{bucket_name}/{object_path}",
        filesystem=pafs.GcsFileSystem(),
    )
