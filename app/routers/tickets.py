# routers/tickets.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from deps import get_current_user, require_role
from supabase_client import supabase, supabase_admin

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TicketCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str
    priority: str = "medium"
    office_id: Optional[int] = None


def find_best_technician(category: str) -> Optional[str]:
    # 1. Everyone with a skill in this category
    skilled = (
        supabase_admin.table("technician_skills")
        .select("user_id, proficiency_level, skills!inner(category)")
        .eq("skills.category", category)
        .execute()
    )
    if not skilled.data:
        return None

    level_rank = {"expert": 3, "intermediate": 2, "beginner": 1}
    candidate_ids = list({row["user_id"] for row in skilled.data})

    # 2. Narrow to approved + online technicians
    profiles = (
        supabase_admin.table("profiles")
        .select("id, is_online, role, application_status")
        .in_("id", candidate_ids)
        .eq("role", "technician")
        .eq("application_status", "approved")
        .eq("is_online", True)
        .execute()
    )
    eligible_ids = {p["id"] for p in profiles.data}
    if not eligible_ids:
        return None

    # 3. Best proficiency per eligible candidate for this category
    best_level = {}
    for row in skilled.data:
        uid = row["user_id"]
        if uid not in eligible_ids:
            continue
        lvl = level_rank.get(row["proficiency_level"], 0)
        best_level[uid] = max(best_level.get(uid, 0), lvl)

    # 4. Current open workload per candidate, for tiebreaking
    workload = (
        supabase_admin.table("tickets")
        .select("assigned_to")
        .in_("assigned_to", list(best_level.keys()))
        .in_("status", ["assigned", "in_progress"])
        .execute()
    )
    open_count = {}
    for row in workload.data:
        open_count[row["assigned_to"]] = open_count.get(row["assigned_to"], 0) + 1

    # 5. Rank: highest skill level first, then fewest open tickets
    ranked = sorted(
        best_level.keys(),
        key=lambda uid: (-best_level[uid], open_count.get(uid, 0)),
    )
    return ranked[0] if ranked else None


@router.post("")
def create_ticket(payload: TicketCreate, current_user=Depends(get_current_user)):
    ticket_row = {
        "title": payload.title,
        "description": payload.description,
        "category": payload.category,
        "priority": payload.priority,
        "office_id": payload.office_id,
        "submitted_by": current_user["id"],
    }

    match = find_best_technician(payload.category)
    if match:
        ticket_row["assigned_to"] = match
        ticket_row["status"] = "assigned"

    result = supabase.table("tickets").insert(ticket_row).execute()
    return result.data[0]


@router.get("/mine")
def my_tickets(current_user=Depends(get_current_user)):
    result = (
        supabase.table("tickets")
        .select("*")
        .eq("submitted_by", current_user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.get("/assigned", dependencies=[Depends(require_role("technician"))])
def assigned_tickets(current_user=Depends(get_current_user)):
    result = (
        supabase.table("tickets")
        .select("*")
        .eq("assigned_to", current_user["id"])
        .order("priority", desc=True)
        .execute()
    )
    return result.data


class StatusUpdate(BaseModel):
    status: str


@router.patch("/{ticket_id}/status", dependencies=[Depends(require_role("technician", "supervisor", "admin"))])
def update_status(ticket_id: int, payload: StatusUpdate, current_user=Depends(get_current_user)):
    ticket = supabase_admin.table("tickets").select("*").eq("id", ticket_id).single().execute()
    if not ticket.data:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user["profile"]["role"] == "technician" and ticket.data["assigned_to"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="This ticket isn't assigned to you")

    update = {"status": payload.status}
    if payload.status == "resolved":
        update["resolved_at"] = "now()"

    supabase.table("tickets").update(update).eq("id", ticket_id).execute()
    return {"message": f"Ticket status updated to {payload.status}"}


class ManualAssign(BaseModel):
    technician_id: str


@router.patch("/{ticket_id}/assign", dependencies=[Depends(require_role("supervisor", "admin"))])
def manual_assign(ticket_id: int, payload: ManualAssign):
    supabase_admin.table("tickets").update({
        "assigned_to": payload.technician_id,
        "status": "assigned",
    }).eq("id", ticket_id).execute()
    return {"message": "Ticket reassigned"}