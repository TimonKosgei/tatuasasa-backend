from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr
from supabase_client import supabase
 
router = APIRouter(prefix="/auth", tags=["auth"])
 
 
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
 
 
class SignInRequest(BaseModel):
    email: EmailStr
    password: str
 
 
@router.post("/signup")
def sign_up(payload: SignUpRequest):
    try:
        result = supabase.auth.sign_up({
            "email": payload.email,
            "password": payload.password,
            "options": {"data": {"full_name": payload.full_name}},
        })
        return {
            "message": "Check your email to confirm your account",
            "user_id": result.user.id if result.user else None,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
 
 
@router.post("/signin")
def sign_in(payload: SignInRequest):
    try:
        result = supabase.auth.sign_in_with_password({
            "email": payload.email,
            "password": payload.password,
        })
        return {
            "access_token": result.session.access_token,
            "refresh_token": result.session.refresh_token,
            "expires_in": result.session.expires_in,
            "user": {"id": result.user.id, "email": result.user.email},
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid email or password")
 
 
@router.post("/signout")
def sign_out(authorization: str = Header(...)):
    try:
        supabase.auth.sign_out()
        return {"message": "Signed out successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
