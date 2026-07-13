import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException
from supabase_client import supabase_admin

async def check_assignment_timeout(ticket_id: int, assigned_tech_id: str):
    """
    Monitors the ticket. If the technician does not Accept or Reject 
    within 180 seconds, it logs a system timeout and cascades assignment.
    """
    # Wait asynchronously for 3 minutes (180 seconds)
    await asyncio.sleep(180)
    
    # Fetch the ticket state after the wait
    ticket_query = supabase_admin.table("tickets").select("id", "status", "assigned_to").eq("id", ticket_id).single().execute()
    ticket = ticket_query.data
    
    if not ticket:
        return  # Ticket was deleted or resolved already
        
    # If the ticket is still 'assigned' to the same technician who ignored it:
    if ticket["status"] == "assigned" and ticket["assigned_to"] == assigned_tech_id:
        print(f"[TIMEOUT] Ticket #{ticket_id} ignored by {assigned_tech_id}. Auto-reassigning...")
        
        # Trigger the cascading fallback
        await auto_assign_ticket_to_best_tech(
            ticket_id=ticket_id,
            last_tech_id=assigned_tech_id,
            rejection_reason="System Timeout: Technician did not respond within 3 minutes."
        )


async def auto_assign_ticket_to_best_tech(ticket_id: int, last_tech_id: str = None, rejection_reason: str = None, background_tasks = None):
    """
    Finds the best available technician, excluding prior rejections.
    If no matching technicians remain, routes directly to the department supervisor.
    """
    # 1. Fetch ticket category and rejection metadata
    ticket_query = supabase_admin.table("tickets").select("id", "category", "rejected_by", "rejection_reasons").eq("id", ticket_id).single().execute()
    ticket = ticket_query.data
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    category = ticket["category"]
    rejected_by = ticket["rejected_by"] or []
    rejection_reasons = ticket["rejection_reasons"] or []

    # If triggered by a rejection, append details with the technician's name
    if last_tech_id:
        if last_tech_id not in rejected_by:
            rejected_by.append(last_tech_id)
        
        # Look up technician's name to make the audit log helpful for supervisors
        tech_profile = supabase_admin.table("profiles").select("full_name").eq("id", last_tech_id).single().execute()
        tech_name = tech_profile.data.get("full_name") if tech_profile.data else "Unknown Tech"

        rejection_reasons.append({
            "tech_id": last_tech_id,
            "full_name": tech_name,
            "reason": rejection_reason or "Rejected by technician",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    # 2. Query all ONLINE technicians
    techs_query = (
        supabase_admin.table("profiles")
        .select("id, full_name, role, is_online")
        .eq("role", "technician")
        .eq("is_online", True)
        .execute()
    )
    
    candidates = []
    for tech in techs_query.data:
        # Strictly skip if they've already rejected this ticket
        if tech["id"] in rejected_by:
            continue
            
        # Verify if they have the specific skill for this category
        skills_query = (
            supabase_admin.table("technician_skills")
            .select("proficiency_level, skills(category)")
            .eq("user_id", tech["id"])
            .execute()
        )
        
        has_skill = False
        proficiency_weight = 1
        for user_skill in skills_query.data:
            # Matches category tags (e.g., hardware, network)
            if user_skill["skills"] and user_skill["skills"]["category"].lower() == category.lower():
                has_skill = True
                level = user_skill["proficiency_level"]
                if level == "expert":
                    proficiency_weight = 3
                elif level == "intermediate":
                    proficiency_weight = 2
                break
                
        if has_skill:
            # Check their current active ticket load (Load-balancing)
            active_tickets = (
                supabase_admin.table("tickets")
                .select("id", count="exact")
                .eq("assigned_to", tech["id"])
                .in_("status", ["assigned", "in_progress"])
                .execute()
            )
            workload = active_tickets.count or 0
            
            candidates.append({
                "id": tech["id"],
                "proficiency_weight": proficiency_weight,
                "workload": workload
            })

    # 3. Handle Assignment Flow
    if candidates:
        # Sort by: 1. Lowest workload first, 2. Highest skill level second
        sorted_candidates = sorted(candidates, key=lambda x: (x["workload"], -x["proficiency_weight"]))
        next_best_tech = sorted_candidates[0]
        
        supabase_admin.table("tickets").update({
            "assigned_to": next_best_tech["id"],
            "status": "assigned",
            "rejected_by": rejected_by,
            "rejection_reasons": rejection_reasons
        }).eq("id", ticket_id).execute()
        
        # Schedule the 3-minute check if background_tasks context is provided
        if background_tasks:
            background_tasks.add_task(check_assignment_timeout, ticket_id, next_best_tech["id"])
        
        return {"assigned_to": next_best_tech["id"], "role": "technician"}
    
    else:
        # Fallback: Nobody left! Find the Supervisor of the department responsible for this category
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
        
        # Fallback to the first supervisor if no department match works
        if not assigned_supervisor and supervisor_query.data:
            assigned_supervisor = supervisor_query.data[0]["id"]

        supabase_admin.table("tickets").update({
            "assigned_to": assigned_supervisor,
            "status": "open",  # Set back to open for manual review
            "rejected_by": rejected_by,
            "rejection_reasons": rejection_reasons
        }).eq("id", ticket_id).execute()
        
        return {"assigned_to": assigned_supervisor, "role": "supervisor"}