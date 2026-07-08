# routers/tickets.py
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator, model_validator

from deps import get_current_user, require_role
from supabase_client import supabase, supabase_admin

router = APIRouter(prefix="/tickets", tags=["tickets"])

VALID_CATEGORIES = {"hardware", "network", "software", "printers", "security"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
VALID_STATUSES = {"open", "assigned", "in_progress", "resolved", "closed"}


class TicketCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str
    priority: str = "medium"
    location_building: Optional[str] = None
    location_floor: Optional[str] = None
    location_room: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty")
        return v

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        return v

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, v: str) -> str:
        if v not in VALID_PRIORITIES:
            raise ValueError(f"priority must be one of {sorted(VALID_PRIORITIES)}")
        return v


class StatusUpdate(BaseModel):
    status: str
    steps: Optional[list[str]] = None
    comment: Optional[str] = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
        return v

    @model_validator(mode="after")
    def steps_required_if_resolved(self):
        if self.status == "resolved":
            clean = [s.strip() for s in (self.steps or []) if s.strip()]
            if not clean:
                raise ValueError("At least one resolution step is required when marking a ticket resolved")
            self.steps = clean
        return self


class ManualAssign(BaseModel):
    technician_id: str


def find_best_technician(category: str) -> Optional[str]:
    """
    Matching order:
      1. Everyone with a skill in this category
      2. Narrowed to approved + online technicians
      3. Ranked by proficiency (expert > intermediate > beginner)
      4. Tiebroken by current open workload (fewer open tickets wins)
    Returns None if nobody qualifies — ticket stays unassigned for a
    supervisor to assign manually.
    """
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

    best_level = {}
    for row in skilled.data:
        uid = row["user_id"]
        if uid not in eligible_ids:
            continue
        lvl = level_rank.get(row["proficiency_level"], 0)
        best_level[uid] = max(best_level.get(uid, 0), lvl)

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
        "submitted_by": current_user["id"],
        "location_building": payload.location_building,
        "location_floor": payload.location_floor,
        "location_room": payload.location_room,
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


@router.get("", dependencies=[Depends(require_role("supervisor", "admin"))])
def list_all_tickets(status: Optional[str] = None):
    """Full ticket board — for Supervisor/Admin dashboards."""
    query = supabase_admin.table("tickets").select("*").order("created_at", desc=True)
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {sorted(VALID_STATUSES)}")
        query = query.eq("status", status)
    result = query.execute()
    return result.data


@router.patch("/{ticket_id}/status", dependencies=[Depends(require_role("technician", "supervisor", "admin"))])
def update_status(ticket_id: int, payload: StatusUpdate, current_user=Depends(get_current_user)):
    ticket = supabase_admin.table("tickets").select("*").eq("id", ticket_id).single().execute()
    if not ticket.data:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if current_user["profile"]["role"] == "technician" and ticket.data["assigned_to"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="This ticket isn't assigned to you")

    update = {"status": payload.status}
    if payload.status == "resolved":
        update["resolved_at"] = datetime.now(timezone.utc).isoformat()
        update["resolution_notes"] = payload.comment

    supabase.table("tickets").update(update).eq("id", ticket_id).execute()

    if payload.status == "resolved" and payload.steps:
        # Replace any previous steps (e.g. a correction) rather than appending
        supabase_admin.table("resolution_steps").delete().eq("ticket_id", ticket_id).execute()
        rows = [
            {"ticket_id": ticket_id, "step_number": i + 1, "description": step}
            for i, step in enumerate(payload.steps)
        ]
        supabase_admin.table("resolution_steps").insert(rows).execute()

    return {"message": f"Ticket status updated to {payload.status}"}


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, current_user=Depends(get_current_user)):
    ticket = supabase_admin.table("tickets").select("*").eq("id", ticket_id).single().execute()
    if not ticket.data:
        raise HTTPException(status_code=404, detail="Ticket not found")

    role = current_user["profile"]["role"]
    is_owner = ticket.data["submitted_by"] == current_user["id"]
    is_assignee = ticket.data["assigned_to"] == current_user["id"]
    if role not in ("supervisor", "admin") and not (is_owner or is_assignee):
        raise HTTPException(status_code=403, detail="You don't have access to this ticket")

    steps = (
        supabase_admin.table("resolution_steps")
        .select("step_number, description")
        .eq("ticket_id", ticket_id)
        .order("step_number")
        .execute()
    )

    return {**ticket.data, "resolution_steps": steps.data}


@router.patch("/{ticket_id}/assign", dependencies=[Depends(require_role("supervisor", "admin"))])
def manual_assign(ticket_id: int, payload: ManualAssign):
    supabase_admin.table("tickets").update({
        "assigned_to": payload.technician_id,
        "status": "assigned",
    }).eq("id", ticket_id).execute()
    return {"message": "Ticket reassigned"}