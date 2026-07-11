# routers/skills.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator

from deps import get_current_user, require_role
from supabase_client import supabase_admin

router = APIRouter(prefix="/skills", tags=["skills"])

VALID_CATEGORIES = {"hardware", "network", "software", "printers", "security"}


class SkillCreate(BaseModel):
    name: str
    category: str

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Skill name cannot be empty")
        return v

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        return v


@router.get("")
def list_skills(current_user=Depends(get_current_user)):
    result = supabase_admin.table("skills").select("*").order("category").order("name").execute()
    return result.data


@router.post("", dependencies=[Depends(require_role("admin"))])
def create_skill(payload: SkillCreate):
    try:
        result = supabase_admin.table("skills").insert(payload.model_dump()).execute()
        return result.data[0]
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="A skill with this name already exists")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{skill_id}", dependencies=[Depends(require_role("admin"))])
def delete_skill(skill_id: int):
    in_use = (
        supabase_admin.table("technician_skills")
        .select("user_id", count="exact")
        .eq("skill_id", skill_id)
        .execute()
    )
    if in_use.count and in_use.count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete — {in_use.count} technician(s) currently list this skill",
        )
    supabase_admin.table("skills").delete().eq("id", skill_id).execute()
    return {"message": "Skill deleted"}