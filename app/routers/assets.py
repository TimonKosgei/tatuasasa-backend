# routers/assets.py
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator

from deps import get_current_user, require_role
from supabase_client import  supabase_admin

router = APIRouter(prefix="/assets", tags=["assets"])

VALID_CATEGORIES = {"hardware", "network", "software", "printers", "security"}
VALID_STATUSES = {"active", "under_repair", "decommissioned", "disposed"}


class AssetCreate(BaseModel):
    name: str
    category: str
    asset_tag: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    building_id: Optional[int] = None
    office_id: Optional[int] = None
    department_id: Optional[int] = None
    acquired_on: Optional[str] = None

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Asset name cannot be empty")
        return v

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        return v


class AssetStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
        return v


@router.get("")
def list_assets(
    search: Optional[str] = None,
    office_id: Optional[int] = None,
    building_id: Optional[int] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """
    Used by the technician's resolve-ticket asset picker — search is a plain
    ilike match on name/asset_tag so 'laserjet' or a partial tag both work.
    """
    query = supabase_admin.table("assets").select("*").order("name")
    if search:
        query = query.or_(f"name.ilike.%{search}%,asset_tag.ilike.%{search}%")
    if office_id:
        query = query.eq("office_id", office_id)
    if building_id:
        query = query.eq("building_id", building_id)
    if category:
        query = query.eq("category", category)
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return result.data


@router.get("/flagged", dependencies=[Depends(require_role("supervisor", "admin"))])
def flagged_assets(min_incidents: int = 3):
    """
    Assets linked to at least `min_incidents` resolved tickets — the
    replace-this-thing worklist. Aggregation is done in Python rather than a
    view for now since the dataset is small; worth moving to a real SQL view
    if this list grows large.
    """
    links = supabase_admin.table("ticket_assets").select("asset_id").execute()
    counts: dict[int, int] = {}
    for row in links.data:
        counts[row["asset_id"]] = counts.get(row["asset_id"], 0) + 1

    flagged_ids = [aid for aid, count in counts.items() if count >= min_incidents]
    if not flagged_ids:
        return []

    assets = supabase_admin.table("assets").select("*").in_("id", flagged_ids).execute()
    return [
        {**asset, "incident_count": counts[asset["id"]]}
        for asset in assets.data
    ]


@router.get("/{asset_id}/tickets", dependencies=[Depends(require_role("supervisor", "admin"))])
def asset_ticket_history(asset_id: int):
    links = supabase_admin.table("ticket_assets").select("ticket_id").eq("asset_id", asset_id).execute()
    ticket_ids = [row["ticket_id"] for row in links.data]
    if not ticket_ids:
        return []
    tickets = (
        supabase_admin.table("tickets")
        .select("id, title, status, created_at, resolved_at")
        .in_("id", ticket_ids)
        .order("created_at", desc=True)
        .execute()
    )
    return tickets.data


@router.post("", dependencies=[Depends(require_role("admin"))])
def create_asset(payload: AssetCreate):
    try:
        result = supabase_admin.table("assets").insert(payload.model_dump(exclude_none=True)).execute()
        return result.data[0]
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="An asset with this tag already exists")
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{asset_id}/status", dependencies=[Depends(require_role("admin"))])
def update_asset_status(asset_id: int, payload: AssetStatusUpdate):
    result = supabase_admin.table("assets").update({"status": payload.status}).eq("id", asset_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Asset not found")
    return result.data[0]