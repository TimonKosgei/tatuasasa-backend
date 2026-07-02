from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, admin
from supabase_client import supabase_admin, supabase

app = FastAPI(title="Tatua Sasa API")
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # your React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
app.include_router(auth.router)
app.include_router(admin.router)
 
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/users")
def get_users():
    try:
        response = supabase_admin.table("profiles").select("*").execute()
        users = response.data if response.data else []
        return users
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))