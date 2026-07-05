from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
from typing import List
from deps import get_current_user
from supabase_client import supabase, supabase_admin

router = APIRouter(prefix="/technicians", tags=["technicians"])


class SkillInput(BaseModel):
    skill_id: int
    level: int = 1

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
    """Used by TechnicianApply.jsx to decide which view to render."""
    profile = current_user["profile"]

    skills_result = (
        supabase_admin.table("technician_skills")
        .select("skill_id, proficiency_level, skills(name, category)")
        .eq("user_id", current_user["id"])
        .execute()
    )

    return {
        "application_status": profile["application_status"],
        "requested_role": profile.get("requested_role"),
        "supervisor_id": profile.get("supervisor_id"),
        "skills": skills_result.data,
    }


@router.post("/apply")
def apply_as_technician(payload: ApplyRequest, current_user=Depends(get_current_user)):
    profile = current_user["profile"]

    # 1. Block re-applying while something is already in flight or done
    if profile["application_status"] in ("pending", "approved"):
        raise HTTPException(
            status_code=400,
            detail=f"You already have a {profile['application_status']} application",
        )

    # 2. Confirm the chosen supervisor is actually a supervisor
    supervisor = (
        supabase_admin.table("profiles")
        .select("id, role")
        .eq("id", payload.supervisor_id)
        .single()
        .execute()
    )
    if not supervisor.data or supervisor.data["role"] != "supervisor":
        raise HTTPException(status_code=400, detail="Selected supervisor is not valid")

    # 3. Confirm every skill_id actually exists in the catalog
    skill_ids = [s.skill_id for s in payload.skills]
    existing_skills = (
        supabase_admin.table("skills")
        .select("id")
        .in_("id", skill_ids)
        .execute()
    )
    found_ids = {row["id"] for row in existing_skills.data}
    missing = set(skill_ids) - found_ids
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown skill id(s): {sorted(missing)}")

    # 4. Replace any previous skill selections (e.g. a re-apply after rejection)
    supabase_admin.table("technician_skills").delete().eq("user_id", current_user["id"]).execute()

    rows = [
        {
            "user_id": current_user["id"],
            "skill_id": s.skill_id,
            "proficiency_level": {1: "beginner", 2: "intermediate", 3: "expert"}[s.level],
        }
        for s in payload.skills
    ]
    supabase_admin.table("technician_skills").insert(rows).execute()

    # 5. Flip the application into pending
    supabase_admin.table("profiles").update({
        "application_status": "pending",
        "requested_role": "technician",
        "supervisor_id": payload.supervisor_id,
    }).eq("id", current_user["id"]).execute()

    return {"message": "Application submitted", "application_status": "pending"}