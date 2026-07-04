from fastapi import Header, HTTPException, Depends
from supabase_client import supabase, supabase_admin
 
async def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.replace("Bearer ", "")
 
    try:
        user_response = supabase.auth.get_user(token)
        user =  user_response.user
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
 
    profile = (
        supabase_admin.table("profiles")
        .select("*")
        .eq("id", user.id)
        .single()
        .execute()
    )
    return {"id": user.id, "email": user.email, "profile": profile.data}
 
 
def require_role(*allowed_roles):
    """Usage: Depends(require_role('admin', 'supervisor'))"""
    def role_checker(current_user=Depends(get_current_user)):
        if current_user["profile"]["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker

