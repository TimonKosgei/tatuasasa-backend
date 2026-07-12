from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from deps import get_current_user, require_role
from supabase_client import supabase
from supabase_client import supabase_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Create supervisor ----------

class CreateSupervisorRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    department: str


@router.post("/supervisors")
def create_supervisor(
    payload: CreateSupervisorRequest, current_user=Depends(require_role("admin"))
):
    try:
        result = supabase_admin.auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,  # skip confirmation email, admin is vouching
            "user_metadata": {"full_name": payload.full_name},
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    new_id = result.user.id

    # Trigger already inserted a 'staff'/'approved' row on auth.users insert —
    # overwrite role/department here since this is an admin-created supervisor
    supabase_admin.table("profiles").update({
        "role": "supervisor",
        "department": payload.department,
        "status": "approved",
    }).eq("id", new_id).execute()

    return {"message": "Supervisor created", "user_id": new_id}


# ---------- List supervisors ----------

@router.get("/supervisors")
def list_supervisors(current_user=Depends(require_role("admin"))):
    result = (
        supabase_admin.table("profiles")
        .select("id, full_name, department, created_at")
        .eq("role", "supervisor")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


# ---------- Unassigned technicians ----------

@router.get("/technicians/unassigned")
def list_unassigned(current_user=Depends(require_role("admin"))):
    result = (
        supabase_admin.table("profiles")
        .select("*")
        .eq("role", "technician")
        .is_("supervisor_id", "null")
        .execute()
    )
    return result.data


# ---------- Manually assign a supervisor ----------

class AssignSupervisorRequest(BaseModel):
    supervisor_id: str


@router.patch("/technicians/{tech_id}/assign-supervisor")
def assign_supervisor(
    tech_id: str,
    payload: AssignSupervisorRequest,
    current_user=Depends(require_role("admin")),
):
    supervisor = (
        supabase.table("profiles")
        .select("role")
        .eq("id", payload.supervisor_id)
        .single()
        .execute()
    )
    if not supervisor.data or supervisor.data["role"] != "supervisor":
        raise HTTPException(status_code=400, detail="Target user is not a supervisor")

    technician = (
        supabase.table("profiles")
        .select("role")
        .eq("id", tech_id)
        .single()
        .execute()
    )
    if not technician.data or technician.data["role"] != "technician":
        raise HTTPException(status_code=400, detail="Target user is not a technician")

    supabase.table("profiles").update(
        {"supervisor_id": payload.supervisor_id}
    ).eq("id", tech_id).execute()

    return {"message": "Supervisor assigned"}

@router.get("/public/supervisors")
def list_available_supervisors(current_user=Depends(get_current_user)):
    """Exposes a clean list of supervisors for staff application routing."""
    result = supabase_admin.table("profiles").select("id, full_name").eq("role", "supervisor").execute()
    return result.data