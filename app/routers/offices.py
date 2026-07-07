from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from deps import get_current_user, require_role
from supabase_client import supabase_admin

router = APIRouter(prefix="/offices", tags=["offices"])

class OfficeCreate(BaseModel):
    building_id: int
    name: str
    floor: str | None = None
    room_code: str | None = None
    department_id: int | None = None

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Office name cannot be empty")
        return v

@router.get("")
def list_offices(current_user=Depends(get_current_user)):
    result = (
        supabase_admin.table("offices")
        .select("*, buildings(name), departments(name)")
        .order("building_id")
        .execute()
    )
    return result.data

@router.post("", dependencies=[Depends(require_role("admin"))])
def create_office(payload: OfficeCreate):
    result = supabase_admin.table("offices").insert(payload.model_dump()).execute()
    return result.data[0]