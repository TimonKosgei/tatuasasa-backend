from datetime import datetime, timezone
from typing import Optional, List
import random

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, field_validator, model_validator

from deps import get_current_user, require_role
from supabase_client import supabase, supabase_admin

# Import our custom matching and timeout engine
from services.matching import auto_assign_ticket_to_best_tech

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
    asset_ids: Optional[list[int]] = None

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


@router.post("")
async def create_ticket(
    payload: TicketCreate, 
    background_tasks: BackgroundTasks, 
    current_user=Depends(get_current_user)
):
    # Initialize the ticket row as unassigned and open
    ticket_row = {
        "title": payload.title,
        "description": payload.description,
        "category": payload.category,
        "priority": payload.priority,
        "submitted_by": current_user["id"],
        "location_building": payload.location_building,
        "location_floor": payload.location_floor,
        "location_room": payload.location_room,
        "status": "open"
    }

    # Insert the ticket to generate its real ID
    insert_result = supabase.table("tickets").insert(ticket_row).execute()
    if not insert_result.data:
        raise HTTPException(status_code=500, detail="Failed to initialize ticket submission.")
    
    new_ticket = insert_result.data[0]

    # Run matching engine to automatically assign the ticket and kick off the 3-minute timeout task
    await auto_assign_ticket_to_best_tech(
        ticket_id=new_ticket["id"],
        background_tasks=background_tasks
    )

    # Fetch the newly assigned ticket details to return back to the frontend
    updated_query = supabase_admin.table("tickets").select("*").eq("id", new_ticket["id"]).single().execute()
    return updated_query.data


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
async def update_status(
    ticket_id: int, 
    payload: StatusUpdate, 
    background_tasks: BackgroundTasks, 
    current_user=Depends(get_current_user)
):
    ticket = supabase_admin.table("tickets").select("*").eq("id", ticket_id).single().execute()
    if not ticket.data:
        raise HTTPException(status_code=404, detail="Ticket not found")

    role = current_user["profile"]["role"]
    if role == "technician" and ticket.data["assigned_to"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="This ticket isn't assigned to you")

    # --- CASE A: TECHNICIAN ESCALATES THE TICKET ---
    if payload.status == "escalated":
        # 1. Locate the department supervisor for this category
        category = ticket.data["category"]
        supervisor_query = (
            supabase_admin.table("profiles")
            .select("id, department")
            .eq("role", "supervisor")
            .execute()
        )
        
        assigned_supervisor = None
        for sup in supervisor_query.data:
            if sup["department"] and sup["department"].lower() in category.lower():
                assigned_supervisor = sup["id"]
                break
        
        if not assigned_supervisor and supervisor_query.data:
            assigned_supervisor = supervisor_query.data[0]["id"]

        # 2. Re-route to the supervisor, set status back to open, and flag as escalated
        supabase_admin.table("tickets").update({
            "status": "open",
            "assigned_to": assigned_supervisor,
            "is_escalated": True,
            "escalated_by": current_user["id"]
        }).eq("id", ticket_id).execute()

        # 3. Append the escalation event to the rejection/audit reasons trail
        rejection_reasons = ticket.data["rejection_reasons"] or []
        rejection_reasons.append({
            "tech_id": current_user["id"],
            "full_name": current_user["profile"].get("full_name", "Technician"),
            "reason": payload.comment or "Escalated: Issue requires supervisor intervention.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        supabase_admin.table("tickets").update({
            "rejection_reasons": rejection_reasons
        }).eq("id", ticket_id).execute()

        return {
            "message": "Ticket successfully escalated to supervisor.",
            "assigned_supervisor": assigned_supervisor
        }

    # --- CASE B: TICKET IS REJECTED (STATUS CHANGED TO OPEN) ---
    elif payload.status == "open":
        cascade_result = await auto_assign_ticket_to_best_tech(
            ticket_id=ticket_id,
            last_tech_id=current_user["id"],
            rejection_reason=payload.comment or "Rejected manually by assigned technician.",
            background_tasks=background_tasks
        )
        return {
            "message": "Ticket status updated to open. Reassignment cascade initiated.",
            "assigned_to": cascade_result["assigned_to"],
            "role_assigned": cascade_result["role"]
        }

    # --- CASE C: TICKET IS RESOLVED (SAVE EVERYTHING AS SINGLE NOTE) ---
    elif payload.status == "resolved":
        # Format steps array into a single "OneNote" styled markdown block
        formatted_steps = ""
        if payload.steps:
            formatted_steps = "\n".join([f"{idx + 1}. {step}" for idx, step in enumerate(payload.steps)])

        # Combine steps and comments into single database column
        full_resolution_note = ""
        if formatted_steps:
            full_resolution_note += f"### Resolution Steps:\n{formatted_steps}\n\n"
        if payload.comment:
            full_resolution_note += f"### Additional Notes:\n{payload.comment}"

        # Save updates
        supabase.table("tickets").update({
            "status": "resolved",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolution_notes": full_resolution_note.strip()
        }).eq("id", ticket_id).execute()

        # Track linked assets
        if payload.asset_ids:
            existing = supabase_admin.table("assets").select("id").in_("id", payload.asset_ids).execute()
            found_ids = {row["id"] for row in existing.data}
            missing = set(payload.asset_ids) - found_ids
            if missing:
                raise HTTPException(status_code=400, detail=f"Unknown asset id(s): {sorted(missing)}")

            supabase_admin.table("ticket_assets").delete().eq("ticket_id", ticket_id).execute()
            rows = [{"ticket_id": ticket_id, "asset_id": aid} for aid in payload.asset_ids]
            supabase_admin.table("ticket_assets").insert(rows).execute()

        return {"message": "Ticket successfully marked as resolved and logged."}

    # --- CASE D: DEFAULT STATUS TRANSITIONS (E.G. IN_PROGRESS) ---
    else:
        supabase.table("tickets").update({"status": payload.status}).eq("id", ticket_id).execute()
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

    # Fetch linked assets
    linked = supabase_admin.table("ticket_assets").select("asset_id").eq("ticket_id", ticket_id).execute()
    asset_ids = [row["asset_id"] for row in linked.data]
    assets_data = []
    if asset_ids:
        assets_result = supabase_admin.table("assets").select("id, name, asset_tag").in_("id", asset_ids).execute()
        assets_data = assets_result.data

    # Return resolution_notes as part of ticket.data directly (no resolution_steps table required)
    return {**ticket.data, "affected_assets": assets_data}


@router.patch("/{ticket_id}/assign", dependencies=[Depends(require_role("supervisor", "admin"))])
async def manual_assign(
    ticket_id: int, 
    payload: ManualAssign, 
    background_tasks: BackgroundTasks
):
    supabase_admin.table("tickets").update({
        "assigned_to": payload.technician_id,
        "status": "assigned",
    }).eq("id", ticket_id).execute()

    # Manual assignments get their own 3-minute check-in timer
    await auto_assign_ticket_to_best_tech(
        ticket_id=ticket_id,
        background_tasks=background_tasks
    )

    return {"message": "Ticket reassigned and 3-minute monitoring timer configured."}