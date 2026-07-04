from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
from deps import get_current_user, require_role
from supabase_client import supabase

router = APIRouter(prefix="/departments", tags=["departments"])


class DepartmentCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Department name cannot be empty")
        return v


class DepartmentUpdate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Department name cannot be empty")
        return v


@router.get("")
def list_departments(current_user=Depends(get_current_user)):
    """Any signed-in user can list departments (needed for signup/apply dropdowns)."""
    result = supabase.table("departments").select("*").order("name").execute()
    return result.data


@router.post("", dependencies=[Depends(require_role("admin"))])
def create_department(payload: DepartmentCreate):
    try:
        result = supabase.table("departments").insert({"name": payload.name}).execute()
        return result.data[0]
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="A department with this name already exists")
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{department_id}", dependencies=[Depends(require_role("admin"))])
def update_department(department_id: int, payload: DepartmentUpdate):
    try:
        result = (
            supabase.table("departments")
            .update({"name": payload.name})
            .eq("id", department_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Department not found")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="A department with this name already exists")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{department_id}", dependencies=[Depends(require_role("admin"))])
def delete_department(department_id: int):
    # Look up the department first so we can check usage by name
    # (profiles.department currently stores the name as text, not a foreign key)
    dept = supabase.table("departments").select("*").eq("id", department_id).single().execute()
    if not dept.data:
        raise HTTPException(status_code=404, detail="Department not found")

    in_use = (
        supabase.table("profiles")
        .select("id", count="exact")
        .eq("department", dept.data["name"])
        .execute()
    )
    if in_use.count and in_use.count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete — {in_use.count} user(s) are assigned to this department",
        )

    supabase.table("departments").delete().eq("id", department_id).execute()
    return {"message": "Department deleted"}