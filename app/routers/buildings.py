from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from deps import get_current_user, require_role
from supabase_client import supabase_admin

router = APIRouter(prefix="/buildings", tags=["buildings"])

class BuildingCreate(BaseModel):
    name: str
    county: str | None = None

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Building name cannot be empty")
        return v

@router.get("")
def list_buildings(current_user=Depends(get_current_user)):
    result = supabase_admin.table("buildings").select("*").order("name").execute()
    return result.data

@router.post("", dependencies=[Depends(require_role("admin"))])
def create_building(payload: BuildingCreate):
    result = supabase_admin.table("buildings").insert(payload.model_dump()).execute()
    return result.data[0]

@router.patch("/{building_id}", dependencies=[Depends(require_role("admin"))])
def update_building(building_id: str, payload: BuildingCreate):
    result = supabase_admin.table("buildings").update(payload.model_dump()).eq("id", building_id).execute()
    return result.data[0]

