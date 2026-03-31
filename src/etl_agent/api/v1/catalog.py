"""Catalog management API — browse and annotate the Glue Data Catalog.

Endpoints:
  GET    /api/v1/catalog              List all registered Glue entities
  GET    /api/v1/catalog/{name}       Get one entity with full schema
  POST   /api/v1/catalog              Register a new entity manually
  PUT    /api/v1/catalog/{name}       Update description / classification
  DELETE /api/v1/catalog/{name}       Remove entity from Glue catalog

The Glue Crawler auto-populates schemas; these endpoints are mainly used by
admins to add business metadata (descriptions, classification) on top of what
the Crawler discovered, and to query the catalog from the UI Catalog tab.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from etl_agent.core.data_catalog import DataEntity, get_catalog
from etl_agent.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/catalog", response_model=list[DataEntity])
async def list_catalog() -> list[DataEntity]:
    """List all datasets registered in the Glue Data Catalog."""
    return get_catalog().list_entities()


@router.get("/catalog/{name}", response_model=DataEntity)
async def get_catalog_entity(name: str) -> DataEntity:
    """Get a single dataset by its Glue table name."""
    entity = get_catalog().get_entity(name)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{name}' not found in catalog")
    return entity


@router.post("/catalog", response_model=DataEntity, status_code=201)
async def create_catalog_entity(entity: DataEntity) -> DataEntity:
    """Register a new dataset in the Glue Data Catalog."""
    try:
        get_catalog().create_entity(entity)
        logger.info("catalog_api_create", name=entity.name)
        return entity
    except Exception as exc:
        logger.error("catalog_api_create_failed", name=entity.name, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/catalog/{name}", response_model=DataEntity)
async def update_catalog_entity(name: str, entity: DataEntity) -> DataEntity:
    """Update an existing dataset entry (description, classification, etc.)."""
    if entity.name != name:
        raise HTTPException(
            status_code=400,
            detail=f"Path name '{name}' does not match body name '{entity.name}'",
        )
    existing = get_catalog().get_entity(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Entity '{name}' not found in catalog")
    try:
        get_catalog().update_entity(entity)
        logger.info("catalog_api_update", name=name)
        return entity
    except Exception as exc:
        logger.error("catalog_api_update_failed", name=name, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/catalog/{name}", status_code=204)
async def delete_catalog_entity(name: str) -> None:
    """Remove a dataset from the Glue Data Catalog."""
    existing = get_catalog().get_entity(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Entity '{name}' not found in catalog")
    try:
        get_catalog().delete_entity(name)
        logger.info("catalog_api_delete", name=name)
    except Exception as exc:
        logger.error("catalog_api_delete_failed", name=name, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
