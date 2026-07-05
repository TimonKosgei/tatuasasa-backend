#pending applications, approve/reject, list my team -Supervisor, Admin
from fastapi import APIRouter, HTTPException, Depends
from deps import get_current_user, require_role
from supabase_client import supabase, supabase_admin

router = APIRouter(prefix="/supervisor", tags=["supervisors"])


def _fetch_skills_for(user_id: str):
    result = (
        supabase_admin.table("technician_skills")
        .select("proficiency_level, skills(id, name, category)")
        .eq("user_id", user_id)
        .execute()
    )
    return [
        {
            "id": row["skills"]["id"],
            "name": row["skills"]["name"],
            "category": row["skills"]["category"],
            "level": {"beginner": 1, "intermediate": 2, "expert": 3}[row["proficiency_level"]],
        }
        for row in result.data
    ]

#checks if the current user is allowed to act on the application of the applicant
def _assert_owns_application(current_user, applicant_profile):
    """A supervisor can only act on applications addressed to them. Admins can act on any."""
    if current_user["profile"]["role"] == "admin":
        return
    if applicant_profile["supervisor_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="This application wasn't submitted to you")

#helper to get email of a user by their id 
def _get_email(user_id: str) -> str | None:
    try:
        user = supabase_admin.auth.admin.get_user_by_id(user_id)
        return user.user.email
    except Exception:
        return None

@router.get("/applications/pending", dependencies=[Depends(require_role("supervisor", "admin"))])
def list_pending_applications(current_user=Depends(get_current_user)):
    query = supabase_admin.table("profiles").select("*").eq("application_status", "pending")

    # Admins can optionally see everyone's queue; supervisors only see their own
    if current_user["profile"]["role"] != "admin":
        query = query.eq("supervisor_id", current_user["id"])

    result = query.execute()

    return [
        {
            "id": p["id"],
            "full_name": p["full_name"],
            "email": _get_email(p["id"]),
            "department": p.get("department"),
            "applied_on": p.get("updated_at"),
            "skills": _fetch_skills_for(p["id"]),
        }
        for p in result.data
    ]



@router.get("/technicians", dependencies=[Depends(require_role("supervisor", "admin"))])
def list_my_technicians(current_user=Depends(get_current_user)):
    query = (
        supabase_admin.table("profiles")
        .select("*")
        .eq("role", "technician")
        .eq("application_status", "approved")
    )

    if current_user["profile"]["role"] != "admin":
        query = query.eq("supervisor_id", current_user["id"])

    result = query.execute()

    return [
        {
            "id": p["id"],
            "full_name": p["full_name"],
            "email": _get_email(p["id"]),
            "department": p.get("department"),
            "approved_on": p.get("updated_at"),
            "skills": _fetch_skills_for(p["id"]),
        }
        for p in result.data
    ]


@router.post("/applications/{user_id}/approve", dependencies=[Depends(require_role("supervisor", "admin"))])
def approve_application(user_id: str, current_user=Depends(get_current_user)):
    applicant = supabase_admin.table("profiles").select("*").eq("id", user_id).single().execute()
    if not applicant.data:
        raise HTTPException(status_code=404, detail="Applicant not found")

    _assert_owns_application(current_user, applicant.data)

    if applicant.data["application_status"] != "pending":
        raise HTTPException(status_code=400, detail="This application is not pending")

    supabase_admin.table("profiles").update({
        "role": "technician",
        "application_status": "approved",
    }).eq("id", user_id).execute()

    return {"message": f"{applicant.data['full_name']} approved as technician"}


@router.post("/applications/{user_id}/reject", dependencies=[Depends(require_role("supervisor", "admin"))])
def reject_application(user_id: str, current_user=Depends(get_current_user)):
    applicant = supabase_admin.table("profiles").select("*").eq("id", user_id).single().execute()
    if not applicant.data:
        raise HTTPException(status_code=404, detail="Applicant not found")

    _assert_owns_application(current_user, applicant.data)

    if applicant.data["application_status"] != "pending":
        raise HTTPException(status_code=400, detail="This application is not pending")

    supabase_admin.table("profiles").update({
        "application_status": "rejected",
    }).eq("id", user_id).execute()

    return {"message": f"{applicant.data['full_name']}'s application was rejected"}