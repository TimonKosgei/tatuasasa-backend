import os
import io
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from typing import Literal, List
from pypdf import PdfReader
from google import genai
from google.genai import types
from concurrent.futures import ThreadPoolExecutor

# Project configurations
from supabase_client import supabase
from deps import get_current_user

router = APIRouter(prefix="/ai", tags=["ai-processing"])

# ---- Validation Schemas ----
class SupportItem(BaseModel):
    title: str = Field(description="Concise title for this specific issue or installation guide.")
    category: Literal['hardware', 'network', 'software', 'printers', 'security']
    problem: str = Field(description="The specific error symptom or installation request.")
    probable_causes: str = Field(description="Bullet points detailing what causes this specific issue.")
    possible_solutions: str = Field(description="Numbered step-by-step resolution paths.")

class StructuredDocumentationList(BaseModel):
    articles: List[SupportItem] = Field(description="List of all unique support guides found.")

ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ---- Concurrent Vector Worker ----
def process_and_save_article(article: SupportItem) -> bool:
    """Worker task that handles embedding creation and inserts data in parallel. Returns True if success."""
    compiled_content = (
        f"Problem: {article.problem}\n"
        f"Probable Causes:\n{article.probable_causes}\n"
        f"Possible Solutions:\n{article.possible_solutions}"
    )
    try:
        response = ai_client.models.embed_content(
            model="gemini-embedding-2",
            contents=compiled_content,
            config={"output_dimensionality": 768}
        )
        embedding_vector = response.embeddings[0].values
        
        payload = {
            "title": article.title,
            "content": compiled_content,
            "category": article.category,
            "embedding": embedding_vector
        }
        supabase.table("official_documentation").insert(payload).execute()
        return True
    except Exception as worker_error:
        print(f"[Async Process Error] Failed on item '{article.title}': {str(worker_error)}")
        return False

# ---- Asynchronous Background Engine ----
def pipeline_processing_task(extracted_pages: List[str], job_id: str, filename: str):
    """Background task implementing sliding windows, tracking progress updates in Supabase."""
    print(f"[BACKGROUND TASK START] Job ID: {job_id} for File: {filename}")
    
    page_window_size = 3
    prompt = (
        "You are an elite knowledge base architect. Analyze the provided text from an IT support technical log fragment. "
        "Identify and extract EVERY unique guide, problem description, or installation sequence into a structured format."
    )
    
    extracted_articles = []
    
    try:
        # Loop through pages with our sliding chunk window
        for i in range(0, len(extracted_pages), page_window_size):
            chunk_text = "\n".join(extracted_pages[i:i + page_window_size]).strip()
            if not chunk_text:
                continue
                
            try:
                completion = ai_client.models.generate_content(
                    model='gemini-3.5-flash',
                    contents=f"{prompt}\n\n[Text Segment Block]:\n{chunk_text}",
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=StructuredDocumentationList,
                        temperature=0.1
                    )
                )
                data_batch = StructuredDocumentationList.model_validate_json(completion.text)
                extracted_articles.extend(data_batch.articles)
            except Exception as chunk_err:
                print(f"[Chunk Warning] Failed processing page indices {i}-{i+page_window_size}: {str(chunk_err)}")

        if not extracted_articles:
            # Complete task early if nothing relevant could be structured
            supabase.table("ingestion_jobs").update({
                "status": "completed",
                "total_articles_indexed": 0
            }).eq("id", job_id).execute()
            return

        # Concurrency Layer: Mass upload vector components
        success_count = 0
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(process_and_save_article, extracted_articles)
            success_count = sum(1 for r in results if r)

        # Mark job tracking status as fully complete
        supabase.table("ingestion_jobs").update({
            "status": "completed",
            "total_articles_indexed": success_count
        }).eq("id", job_id).execute()
        
        print(f"[BACKGROUND TASK COMPLETE] Job ID: {job_id} successfully mapped.")

    except Exception as fatal_error:
        # Graceful capture: update tracking layout to failed so frontend knows what happened
        print(f"[BACKGROUND TASK FATAL ERROR] {str(fatal_error)}")
        supabase.table("ingestion_jobs").update({
            "status": "failed",
            "error_message": str(fatal_error)
        }).eq("id", job_id).execute()

# ---- Endpoint A: PDF Upload (Trigger) ----
@router.post("/upload-pdf", status_code=202)
async def upload_pdf_document(
    file: UploadFile = File(...), 
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Upload a multi-page PDF document. Returns a job tracking UUID instantly 
    and spins up parsing configurations asynchronously.
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF documents (.pdf) are supported.")

    try:
        pdf_bytes = await file.read()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        
        extracted_pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                extracted_pages.append(text)
                
        if not extracted_pages:
            raise HTTPException(status_code=400, detail="The target PDF contains no indexable text layers.")
            
    except HTTPException:
        raise
    except Exception as parse_err:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF data: {str(parse_err)}")

    # 1. Initialize the Tracking Job row inside Supabase
    try:
        job_init = supabase.table("ingestion_jobs").insert({
            "filename": file.filename,
            "status": "processing"
        }).execute()
        
        job_record = job_init.data[0]
        job_id = job_record["id"]
    except Exception as db_err:
        raise HTTPException(status_code=500, detail=f"Failed to initialize job tracking matrix: {str(db_err)}")

    # 2. Assign the engine worker script task to execute in the background
    background_tasks.add_task(pipeline_processing_task, extracted_pages, job_id, file.filename)

    # Return tracking status payload immediately
    return {
        "message": "File accepted. Processing has started in the background.",
        "job_id": job_id,
        "filename": file.filename,
        "status": "processing",
        "check_status_url": f"/ai/upload-status/{job_id}"
    }

# ---- Endpoint B: Status Polling ----
@router.get("/upload-status/{job_id}")
def get_upload_status(job_id: str, current_user = Depends(get_current_user)):
    """
    Poll this endpoint using the job_id tracking UUID to monitor background ingestion progress.
    """
    try:
        result = supabase.table("ingestion_jobs").select("*").eq("id", job_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Ingestion job record not found.")
        
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database lookup error: {str(e)}")