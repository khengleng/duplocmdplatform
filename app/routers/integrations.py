import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_mutation_rate_limit, require_service_auth
from app.models import CI, Relationship
from app.schemas import CIBulkIngestResult
from app.services.integrations import fetch_netbox_cis, publish_backstage_bulk_cis
from app.services.reconciliation import reconcile_ci_payload

router = APIRouter(prefix="/integrations", tags=["integrations"], dependencies=[Depends(require_service_auth)])
settings = get_settings()


_slug_re = re.compile(r"[^a-z0-9-]+")


def _slugify(value: str) -> str:
    slug = value.lower().strip().replace(" ", "-")
    slug = _slug_re.sub("-", slug)
    return slug.strip("-") or "ci"


@router.get("/status")
def integrations_status() -> dict[str, Any]:
    return {
        "unified_cmdb_name": settings.unified_cmdb_name,
        "netbox": {
            "enabled": settings.netbox_sync_enabled,
            "configured": bool(settings.netbox_sync_url),
            "api_configured": bool(settings.netbox_api_url and settings.netbox_api_token),
        },
        "backstage": {
            "enabled": settings.backstage_sync_enabled,
            "configured": bool(settings.backstage_sync_url),
            "token_configured": bool(settings.backstage_sync_token),
            "legacy_secret_configured": bool(settings.backstage_sync_secret),
        },
    }


@router.get("/backstage/entities")
def backstage_entities(
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cis = list(db.scalars(select(CI).order_by(CI.updated_at.desc()).limit(limit)))

    items = []
    for ci in cis:
        name_slug = _slugify(ci.name)
        items.append(
            {
                "apiVersion": "backstage.io/v1alpha1",
                "kind": "Component",
                "metadata": {
                    "name": f"{name_slug}-{ci.id[:8]}",
                    "title": ci.name,
                    "description": f"CI {ci.id} from {settings.unified_cmdb_name}",
                    "tags": [ci.ci_type.lower(), ci.status.value.lower(), "unifiedcmdb"],
                    "annotations": {
                        "unifiedcmdb.io/ci-id": ci.id,
                        "unifiedcmdb.io/source": ci.source,
                    },
                },
                "spec": {
                    "type": ci.ci_type.lower(),
                    "lifecycle": ci.status.value.lower(),
                    "owner": ci.owner or "group:default/platform-team",
                    "system": settings.unified_cmdb_name,
                },
            }
        )

    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": items,
    }


@router.get("/netbox/export")
def netbox_export(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cis = list(db.scalars(select(CI).order_by(CI.updated_at.desc()).limit(limit)))
    relationships = list(db.scalars(select(Relationship)))

    return {
        "source": settings.unified_cmdb_name,
        "cis": [
            {
                "id": ci.id,
                "name": ci.name,
                "ci_type": ci.ci_type,
                "status": ci.status.value,
                "owner": ci.owner,
                "attributes": ci.attributes,
                "source": ci.source,
                "last_seen_at": ci.last_seen_at.isoformat(),
            }
            for ci in cis
        ],
        "relationships": [
            {
                "source_ci_id": rel.source_ci_id,
                "target_ci_id": rel.target_ci_id,
                "relation_type": rel.relation_type,
                "source": rel.source,
            }
            for rel in relationships
        ],
    }


@router.post(
    "/netbox/import",
    response_model=CIBulkIngestResult,
    dependencies=[Depends(require_mutation_rate_limit)],
)
def netbox_import(
    limit: int = Query(default=500, ge=1, le=5000),
    dry_run: bool = Query(default=False, alias="dryRun"),
    db: Session = Depends(get_db),
) -> CIBulkIngestResult:
    if limit > settings.max_bulk_items:
        raise HTTPException(
            status_code=400,
            detail=f"Requested limit exceeds configured max_bulk_items ({settings.max_bulk_items})",
        )

    try:
        cis = fetch_netbox_cis(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="NetBox integration is not configured") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="NetBox import failed") from exc

    created = 0
    updated = 0
    collisions = 0

    for ci_payload in cis:
        _, is_created, ci_collisions = reconcile_ci_payload(db, source="netbox", payload=ci_payload)
        collisions += ci_collisions
        if is_created:
            created += 1
        else:
            updated += 1

    staged = 0
    if dry_run:
        staged = created + updated
        db.rollback()
    else:
        db.commit()

    return CIBulkIngestResult(
        created=created,
        updated=updated,
        collisions=collisions,
        staged=staged,
        errors=[],
    )


@router.post(
    "/backstage/sync",
    dependencies=[Depends(require_mutation_rate_limit)],
)
def backstage_sync(
    limit: int = Query(default=500, ge=1, le=5000),
    dry_run: bool = Query(default=False, alias="dryRun"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if limit > settings.max_bulk_items:
        raise HTTPException(
            status_code=400,
            detail=f"Requested limit exceeds configured max_bulk_items ({settings.max_bulk_items})",
        )

    cis = list(db.scalars(select(CI).order_by(CI.updated_at.desc()).limit(limit)))
    items = []
    for ci in cis:
        attributes = ci.attributes if isinstance(ci.attributes, dict) else {}
        items.append(
            {
                "id": ci.id,
                "name": ci.name,
                "ci_type": ci.ci_type,
                "owner": ci.owner,
                "status": ci.status.value,
                "sourceSystem": ci.source,
                "environment": attributes.get("environment", "unknown"),
                "supportGroup": attributes.get("support_group"),
                "identities": [
                    {"scheme": "cmdb_ci_id", "value": ci.id},
                    {"scheme": "canonical_name", "value": ci.name},
                ],
                "attributes": attributes,
            }
        )

    result = publish_backstage_bulk_cis(items=items, dry_run=dry_run)
    result["selected"] = len(items)
    return result
