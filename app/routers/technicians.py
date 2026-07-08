# routers/technicians.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
from typing import List

from deps import get_current_user, require_role
from supabase_client import supabase_admin

router = APIRouter(prefix="/technicians", tags=["technicians"])


def _proficiency_to_level(p: str) -> int:
    return {"beginner": 1, "intermediate": 2, "expert": 3}.get(p, 2)


def _level_to_proficiency(level: int) -> str:
    return {1: "beginner", 2: "intermediate", 3: "expert"}[level]


def _fetch_my_skills(user_id: str):
    result = (
        supabase_admin.table("technician_skills")
        .select("skill_id, proficiency_level, skills(name, category)")
        .eq("user_id", user_id)
        .execute()
    )
    return [
        {
            "skill_id": row["skill_id"],
            "name": row["skills"]["name"],
            "category": row["skills"]["category"],
            "level": _proficiency_to_level(row["proficiency_level"]),
        }
        for row in result.data
    ]


# ---------- application flow ----------

class SkillInput(BaseModel):
    skill_id: int
    level: int = 2

    @field_validator("level")
    @classmethod
    def level_in_range(cls, v: int) -> int:
        if v < 1 or v > 3:
            raise ValueError("level must be between 1 and 3")
        return v


class ApplyRequest(BaseModel):
    supervisor_id: str
    skills: List[SkillInput]

    @field_validator("skills")
    @classmethod
    def at_least_one_skill(cls, v: List[SkillInput]) -> List[SkillInput]:
        if len(v) == 0:
            raise ValueError("At least one skill is required")
        return v


@router.get("/application")
def get_my_application(current_user=Depends(get_current_user)):
    profile = current_user["profile"]
    return {
        "application_status": profile["application_status"],
        "requested_role": profile.get("requested_role"),
        "supervisor_id": profile.get("supervisor_id"),
        "skills": _fetch_my_skills(current_user["id"]),
    }


@router.post("/apply")
def apply_as_technician(payload: ApplyRequest, current_user=Depends(get_current_user)):
    profile = current_user["profile"]

    if profile["application_status"] in ("pending", "approved"):
        raise HTTPException(
            status_code=400,
            detail=f"You already have a {profile['application_status']} application",
        )

    supervisor = (
        supabase_admin.table("profiles")
        .select("id, role")
        .eq("id", payload.supervisor_id)
        .single()
        .execute()
    )
    if not supervisor.data or supervisor.data["role"] != "supervisor":
        raise HTTPException(status_code=400, detail="Selected supervisor is not valid")

    skill_ids = [s.skill_id for s in payload.skills]
    existing_skills = supabase_admin.table("skills").select("id").in_("id", skill_ids).execute()
    found_ids = {row["id"] for row in existing_skills.data}
    missing = set(skill_ids) - found_ids
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown skill id(s): {sorted(missing)}")

    supabase_admin.table("technician_skills").delete().eq("user_id", current_user["id"]).execute()
    rows = [
        {
            "user_id": current_user["id"],
            "skill_id": s.skill_id,
            "proficiency_level": _level_to_proficiency(s.level),
        }
        for s in payload.skills
    ]
    supabase_admin.table("technician_skills").insert(rows).execute()

    supabase_admin  .table("profiles").update({
        "application_status": "pending",
        "requested_role": "technician",
        "supervisor_id": payload.supervisor_id,
    }).eq("id", current_user["id"]).execute()

    return {"message": "Application submitted", "application_status": "pending"}


# ---------- approved technician: manage own skills ----------

@router.get("/skills", dependencies=[Depends(require_role("technician"))])
def list_my_skills(current_user=Depends(get_current_user)):
    return _fetch_my_skills(current_user["id"])


@router.post("/skills", dependencies=[Depends(require_role("technician"))])
def add_or_update_my_skill(payload: SkillInput, current_user=Depends(get_current_user)):
    skill = supabase_admin.table("skills").select("id").eq("id", payload.skill_id).execute()
    if not skill.data:
        raise HTTPException(status_code=404, detail="Skill not found")

    supabase_admin.table("technician_skills").upsert({
        "user_id": current_user["id"],
        "skill_id": payload.skill_id,
        "proficiency_level": _level_to_proficiency(payload.level),
    }).execute()

    return {"message": "Skill saved"}


@router.delete("/skills/{skill_id}", dependencies=[Depends(require_role("technician"))])
def remove_my_skill(skill_id: int, current_user=Depends(get_current_user)):
    supabase_admin.table("technician_skills").delete() \
        .eq("user_id", current_user["id"]) \
        .eq("skill_id", skill_id) \
        .execute()
    return {"message": "Skill removed"}


# ---------- availability ----------

class AvailabilityUpdate(BaseModel):
    is_online: bool


@router.patch("/me/availability", dependencies=[Depends(require_role("technician"))])
def set_availability(payload: AvailabilityUpdate, current_user=Depends(get_current_user)):
    supabase_admin.table("profiles").update({
        "is_online": payload.is_online
    }).eq("id", current_user["id"]).execute()
    return {"is_online": payload.is_online}