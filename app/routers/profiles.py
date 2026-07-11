# routers/profiles.py
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator

from deps import get_current_user
from supabase_client import supabase_admin

router = APIRouter(prefix="/me", tags=["profiles"])


class ProfileUpdate(BaseModel):
    """
    Deliberately narrow — only what a person should be able to change about
    themselves. role, application_status, supervisor_id, and is_online are
    excluded on purpose: role changes go through supervisor/admin routes,
    is_online has its own dedicated toggle endpoint in technicians.py, and
    application_status is only ever set by the apply/approve/reject flow.
    """
    full_name: Optional[str] = None
    department_id: Optional[int] = None
    office_id: Optional[int] = None

    @field_validator("full_name")
    @classmethod
    def not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Full name cannot be empty")
        return v


def _resolve_office(office_id: Optional[int]):
    if not office_id:
        return None
    result = (
        supabase_admin.table("offices")
        .select("id, name, floor, buildings(name)")
        .eq("id", office_id)
        .single()
        .execute()
    )
    if not result.data:
        return None
    return {
        "id": result.data["id"],
        "building": result.data["buildings"]["name"] if result.data.get("buildings") else None,
        "floor": result.data.get("floor"),
        "room": result.data["name"],
    }


@router.get("")
def get_my_profile(current_user=Depends(get_current_user)):
    profile = current_user["profile"]
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "full_name": profile["full_name"],
        "role": profile["role"],
        "department_id": profile.get("department_id"),
        "office_id": profile.get("office_id"),
        "supervisor_id": profile.get("supervisor_id"),
        "application_status": profile["application_status"],
        "is_online": profile.get("is_online", False),
        "must_change_password": profile.get("must_change_password", False),
        "office": _resolve_office(profile.get("office_id")),
    }


@router.patch("")
def update_my_profile(payload: ProfileUpdate, current_user=Depends(get_current_user)):
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No changes provided")

    if "department_id" in updates:
        dept = supabase_admin.table("departments").select("id").eq("id", updates["department_id"]).execute()
        if not dept.data:
            raise HTTPException(status_code=400, detail="Department not found")

    if "office_id" in updates:
        office = supabase_admin.table("offices").select("id").eq("id", updates["office_id"]).execute()
        if not office.data:
            raise HTTPException(status_code=400, detail="Office not found")

    result = supabase_admin.table("profiles").update(updates).eq("id", current_user["id"]).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    return get_my_profile(current_user)