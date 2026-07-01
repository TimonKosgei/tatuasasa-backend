from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth
 
app = FastAPI(title="Tatua Sasa API")
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # your React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
app.include_router(auth.router)
 
 
@app.get("/health")
def health():
    return {"status": "ok"}
