"""AWS Glue Data Catalog client — the ETL Agent data model layer.

All schema knowledge lives in the Glue catalog, auto-populated by a Glue
Crawler that scans the Olist CSV files in S3. This module provides a thin
boto3 wrapper that the StoryParserAgent and orchestrator nodes use to:

  - List all registered entities (called in parse_story to give the LLM
    full catalog context for source/target resolution).
  - Look up an entity by S3 path (called in resolve_catalog to retrieve the
    exact column schema for grounded code generation).
  - Create / update / delete entities (used by the catalog admin REST API).

The Glue database name is read from settings — never hardcoded here.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3

from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models representing a catalog entry
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field  # noqa: E402  (after stdlib/third-party)


class DataField(BaseModel):
    """A single column in a dataset."""

    name: str
    type: str


class DataEntity(BaseModel):
    """A dataset registered in the Glue catalog."""

    name: str
    display_name: str = ""
    description: str = ""
    s3_path: str = ""
    format: str = "csv"
    columns: list[DataField] = Field(default_factory=list)
    data_classification: str = "internal"


# ---------------------------------------------------------------------------
# DataCatalogClient
# ---------------------------------------------------------------------------


class DataCatalogClient:
    """Thin boto3 wrapper around the AWS Glue Data Catalog API."""

    def __init__(self) -> None:
        settings = get_settings()
        self._db: str = settings.glue_catalog_database  # never hardcode the string
        self._client = boto3.client("glue", region_name=settings.aws_region)

    # ── Read operations ───────────────────────────────────────────────────────

    def list_entities(self) -> list[DataEntity]:
        """Return all tables registered in the Glue catalog database."""
        try:
            response = self._client.get_tables(DatabaseName=self._db)
            tables = response.get("TableList", [])
            entities = [self._table_to_entity(t) for t in tables]
            logger.info("catalog_list_entities", count=len(entities), database=self._db)
            return entities
        except Exception as exc:
            logger.warning("catalog_list_entities_failed", database=self._db, error=str(exc))
            return []

    def get_entity(self, name: str) -> DataEntity | None:
        """Return a single entity by Glue table name, or None if not found."""
        try:
            response = self._client.get_table(DatabaseName=self._db, Name=name)
            table = response.get("Table", {})
            return self._table_to_entity(table)
        except self._client.exceptions.EntityNotFoundException:
            return None
        except Exception as exc:
            logger.warning("catalog_get_entity_failed", name=name, error=str(exc))
            return None

    def get_entity_by_path(self, s3_path: str) -> DataEntity | None:
        """Return the entity whose S3 StorageDescriptor.Location matches s3_path."""
        entities = self.list_entities()
        # Normalise trailing slash for comparison
        normalised = s3_path.rstrip("/")
        for entity in entities:
            if entity.s3_path.rstrip("/") == normalised:
                return entity
        return None

    # ── Write operations (catalog admin API) ──────────────────────────────────

    def create_entity(self, entity: DataEntity) -> None:
        """Register a new table in the Glue catalog."""
        self._client.create_table(
            DatabaseName=self._db,
            TableInput=self._entity_to_table_input(entity),
        )
        logger.info("catalog_create_entity", name=entity.name, database=self._db)

    def update_entity(self, entity: DataEntity) -> None:
        """Update an existing table in the Glue catalog."""
        self._client.update_table(
            DatabaseName=self._db,
            TableInput=self._entity_to_table_input(entity),
        )
        logger.info("catalog_update_entity", name=entity.name, database=self._db)

    def delete_entity(self, name: str) -> None:
        """Delete a table from the Glue catalog."""
        self._client.delete_table(DatabaseName=self._db, Name=name)
        logger.info("catalog_delete_entity", name=name, database=self._db)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _table_to_entity(table: dict[str, Any]) -> DataEntity:
        """Convert a raw Glue table dict into a DataEntity."""
        sd = table.get("StorageDescriptor", {})
        cols = sd.get("Columns", [])
        columns = [DataField(name=c["Name"], type=c["Type"]) for c in cols]

        # The Glue Crawler stores the S3 folder path in Location
        s3_path = sd.get("Location", "")

        # Detect format from SerDe or InputFormat
        input_format = sd.get("InputFormat", "")
        serde_info = sd.get("SerdeInfo", {})
        serde_lib = serde_info.get("SerializationLibrary", "")
        if "parquet" in input_format.lower() or "parquet" in serde_lib.lower():
            fmt = "parquet"
        elif "orc" in input_format.lower():
            fmt = "orc"
        else:
            fmt = "csv"

        name = table.get("Name", "")
        description = table.get("Description", "")
        parameters = table.get("Parameters", {})
        classification = parameters.get("data_classification", "internal")
        display_name = parameters.get("display_name", name)

        return DataEntity(
            name=name,
            display_name=display_name,
            description=description,
            s3_path=s3_path,
            format=fmt,
            columns=columns,
            data_classification=classification,
        )

    @staticmethod
    def _entity_to_table_input(entity: DataEntity) -> dict[str, Any]:
        """Convert a DataEntity into the Glue TableInput structure."""
        return {
            "Name": entity.name,
            "Description": entity.description,
            "StorageDescriptor": {
                "Columns": [{"Name": f.name, "Type": f.type} for f in entity.columns],
                "Location": entity.s3_path,
                "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                "SerdeInfo": {
                    "SerializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
                    "Parameters": {"separatorChar": ",", "quoteChar": '"'},
                },
            },
            "Parameters": {
                "classification": entity.format,
                "data_classification": entity.data_classification,
                "display_name": entity.display_name,
            },
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_catalog() -> DataCatalogClient:
    """Return the shared DataCatalogClient instance (created once per process)."""
    return DataCatalogClient()
