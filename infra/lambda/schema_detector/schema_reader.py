"""
Schema Reader
=============
Reads column names and types from a CSV or Parquet file stored in S3.

CSV strategy:
  - Files < 1MB: read the whole file for maximum type-inference accuracy.
  - Files >= 1MB: byte-range request for the first 50KB (header + ~200 rows).
  - pyarrow infers types from the sample; results are mapped to Glue types.
  - Columns with < 10 non-null values fall back to "string" (safe default).
  - Float columns with all values at <= 2 decimal places → decimal(10,2).

Parquet strategy:
  - Read the file footer only — exact types, no inference needed.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pyarrow as pa
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# Minimum non-null values in a column before we trust the inferred type.
# Columns with fewer non-null values default to "string".
_MIN_NONNULL = 10

# Mapping from pyarrow type string → Glue/Hive type string
_PA_TO_GLUE: dict[str, str] = {
    "int8": "bigint",
    "int16": "bigint",
    "int32": "bigint",
    "int64": "bigint",
    "uint8": "bigint",
    "uint16": "bigint",
    "uint32": "bigint",
    "uint64": "bigint",
    "float": "double",
    "float16": "double",
    "float32": "double",
    "float64": "double",
    "double": "double",
    "bool_": "boolean",
    "bool": "boolean",
    "date32[day]": "date",
    "date64[ms]": "date",
    "timestamp[ns]": "timestamp",
    "timestamp[us]": "timestamp",
    "timestamp[ms]": "timestamp",
    "string": "string",
    "utf8": "string",
    "large_utf8": "string",
    "large_string": "string",
}


def read_schema(s3_client: Any, bucket: str, key: str) -> list[dict[str, str]] | None:
    """
    Return a list of {"name": ..., "type": ...} dicts representing the file schema.
    Returns None if the file format is unsupported or an error occurs.
    """
    try:
        suffix = key.rsplit(".", 1)[-1].lower() if "." in key else ""
        if suffix == "parquet":
            return _read_parquet_schema(s3_client, bucket, key)
        if suffix in ("csv", "tsv", "txt"):
            return _read_csv_schema(s3_client, bucket, key)
        logger.warning("unsupported_file_format", key=key, suffix=suffix)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("schema_read_error", key=key, error=str(exc))
        return None


# ── Parquet ───────────────────────────────────────────────────────────────────


def _read_parquet_schema(
    s3_client: Any, bucket: str, key: str
) -> list[dict[str, str]]:
    """Read exact types from the Parquet file footer — no data rows needed."""
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data = resp["Body"].read()
    buf = io.BytesIO(data)
    pfile = pq.ParquetFile(buf)
    arrow_schema = pfile.schema_arrow

    return [
        {"name": field.name, "type": _pa_type_to_glue(field.type)}
        for field in arrow_schema
    ]


# ── CSV ───────────────────────────────────────────────────────────────────────


def _read_csv_schema(s3_client: Any, bucket: str, key: str) -> list[dict[str, str]]:
    """Sample up to 200 rows and infer column types via pyarrow."""
    head = s3_client.head_object(Bucket=bucket, Key=key)
    filesize: int = head["ContentLength"]

    if filesize < 1_000_000:
        # Small file — read entirely for best accuracy
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        raw: bytes = resp["Body"].read()
    else:
        # Large file — byte-range first 50KB (header + ~200 typical rows)
        resp = s3_client.get_object(Bucket=bucket, Key=key, Range="bytes=0-51200")
        raw = resp["Body"].read()

    table = _parse_csv_bytes(raw)
    return _arrow_table_to_glue_schema(table)


def _parse_csv_bytes(raw: bytes) -> pa.Table:
    """Parse CSV bytes, gracefully handling a truncated last line."""
    try:
        return pcsv.read_csv(
            io.BytesIO(raw),
            read_options=pcsv.ReadOptions(block_size=len(raw)),
            parse_options=pcsv.ParseOptions(invalid_row_handler=lambda _: "skip"),
        )
    except Exception:  # noqa: BLE001
        # Byte-range may have cut the last line mid-row — drop it and retry
        trimmed = raw[: raw.rfind(b"\n")]
        return pcsv.read_csv(io.BytesIO(trimmed))


def _arrow_table_to_glue_schema(table: pa.Table) -> list[dict[str, str]]:
    """Convert a pyarrow Table's schema into a list of Glue column dicts."""
    columns: list[dict[str, str]] = []

    for i, field in enumerate(table.schema):
        col_data = table.column(i).drop_null()
        nonnull = len(col_data)
        glue_type = "string"  # safe default for low-cardinality columns

        if nonnull >= _MIN_NONNULL:
            glue_type = _pa_type_to_glue(field.type)

            # Promote float/double columns that consistently have <= 2dp → decimal(10,2)
            if glue_type == "double":
                glue_type = _maybe_decimal(col_data) or glue_type

        columns.append({"name": field.name, "type": glue_type})

    return columns


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pa_type_to_glue(pa_type: pa.DataType) -> str:
    """Map a pyarrow DataType to a Glue/Hive type string."""
    key = str(pa_type)
    return _PA_TO_GLUE.get(key, "string")


def _maybe_decimal(col: pa.ChunkedArray) -> str | None:
    """
    Return "decimal(10,2)" if all sampled values have at most 2 decimal places.
    Used to detect financial/price columns that pyarrow infers as float64.
    """
    try:
        # Sample at most 50 values to keep Lambda execution fast
        vals = col.to_pylist()[:50]
        if all(
            isinstance(v, float) and len(str(v).rstrip("0").split(".")[-1]) <= 2
            for v in vals
            if v is not None
        ):
            return "decimal(10,2)"
    except Exception:  # noqa: BLE001
        pass
    return None
