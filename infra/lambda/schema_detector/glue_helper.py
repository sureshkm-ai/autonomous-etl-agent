"""
Glue Catalog Helper
===================
Thin wrappers around boto3 Glue API calls used by the schema detector Lambda.

Functions:
  - table_exists()        — check whether a table is registered in the catalog
  - get_existing_schema() — fetch the column list from an existing Glue table
  - schemas_differ()      — compare old and new schema column maps
"""

from __future__ import annotations

import logging
from typing import Any

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def table_exists(glue_client: Any, database: str, table_name: str) -> bool:
    """Return True if the Glue table exists in the given database."""
    try:
        glue_client.get_table(DatabaseName=database, Name=table_name)
        return True
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "EntityNotFoundException":
            return False
        # Re-raise unexpected errors (e.g. AccessDeniedException)
        raise


def get_existing_schema(
    glue_client: Any, database: str, table_name: str
) -> list[dict[str, str]]:
    """
    Return the column list from an existing Glue table as
    [{"name": ..., "type": ...}, ...].

    For Iceberg tables the columns live in StorageDescriptor.Columns.
    """
    resp = glue_client.get_table(DatabaseName=database, Name=table_name)
    columns: list[dict[str, Any]] = (
        resp["Table"]["StorageDescriptor"]["Columns"]
    )
    return [{"name": c["Name"], "type": c["Type"]} for c in columns]


def schemas_differ(
    old: list[dict[str, str]], new: list[dict[str, str]]
) -> bool:
    """
    Return True if the column sets differ between old and new schema.

    Comparison is by column name AND type.  Adding, removing, or changing
    the type of any column counts as a schema change.
    """
    old_map = {c["name"]: c["type"] for c in old}
    new_map = {c["name"]: c["type"] for c in new}

    if old_map == new_map:
        return False

    # Log what changed for CloudWatch troubleshooting
    added = set(new_map) - set(old_map)
    removed = set(old_map) - set(new_map)
    changed = {
        col
        for col in set(old_map) & set(new_map)
        if old_map[col] != new_map[col]
    }

    logger.info(
        "schema_diff_detail",
        added=sorted(added),
        removed=sorted(removed),
        type_changed=sorted(changed),
    )
    return True
