from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, admin, departments, technicians , supervisors, offices, buildings, tickets, skills, profiles, ai_support, ai_processing
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
app.include_router(departments.router)
app.include_router(technicians.router)
app.include_router(supervisors.router)
app.include_router(buildings.router)
app.include_router(offices.router)
app.include_router(tickets.router)
app.include_router(skills.router)
app.include_router(profiles.router)
app.include_router(ai_support.router) 
app.include_router(ai_processing.router)

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