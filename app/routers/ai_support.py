import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
from google import genai
from groq import Groq

# Reuse your existing project dependencies and cloud client
from deps import get_current_user
from supabase_client import supabase

router = APIRouter(prefix="/ai", tags=["ai-support"])

# Initialize your AI engines using the configurations verified in your seeding script
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

ai_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options={'api_version': 'v1'}
)
groq_client = Groq(api_key=GROQ_API_KEY)


# ---- Pydantic Schemas ----
class SupportQuery(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question cannot be empty or blank spaces")
        return v


class AssistantResponse(BaseModel):
    answer: str
    sources_used: list[str]


# ---- Helper: Matrix Coordinate Math (Gemini V1) ----
def calculate_vector(text: str) -> list[float]:
    try:
        response = ai_client.models.embed_content(
            model="gemini-embedding-2",
            contents=text,
            config={"output_dimensionality": 768}
        )
        return response.embeddings[0].values
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"AI Embedding cluster failed to index input text: {str(e)}"
        )


# ---- Endpoint: Semantic Search & AI Resolution ----
@router.post("/ask", response_model=AssistantResponse)
def analyze_and_respond(payload: SupportQuery):
    """
    Any logged-in user can submit a question. 
    It vectorizes the prompt via Gemini, queries Supabase, and gets a ultra-fast answer from Groq.
    """
    # 1. Transform text to embedding vector array matching our 768-dim database columns
    query_vector = calculate_vector(payload.question)
    
    context_segments = []
    referenced_sources = []
    
    # 2. Match intent parameters using your database RPC layers via your shared supabase client
    try:
        # Query Stream A: Official Documentation
        doc_matches = supabase.rpc(
            "match_documentation",
            {"query_embedding": query_vector, "match_threshold": 0.55, "match_count": 2}
        ).execute()
        
        # Query Stream B: Past Solved Tickets
        ticket_matches = supabase.rpc(
            "match_solved_tickets",
            {"query_embedding": query_vector, "match_threshold": 0.55, "match_count": 2}
        ).execute()
        
        # Parse official manuals matches
        if doc_matches.data:
            for item in doc_matches.data:
                context_segments.append(f"[Official Documentation: {item['title']}]\n{item['content']}")
                referenced_sources.append(item['title'])
                
        # Parse past closed tickets records matches
        if ticket_matches.data:
            for item in ticket_matches.data:
                context_segments.append(f"[Past Resolved Ticket #{item['ticket_id']}]\n{item['searchable_text']}")
                referenced_sources.append(f"Ticket #{item['ticket_id']}")
                
    except Exception as db_error:
        # Graceful degradation: Log error and allow generation to rely on the base model's domain knowledge
        print(f"[Database Warning] Vector search RPC failure: {str(db_error)}")

    # 3. Compile context payload text blocks
    context_material = "\n\n---\n\n".join(context_segments)
    
    system_prompt = (
        "You are an elite IT support technician AI agent. Your mission is to solve the incoming internal workplace ticket request.\n"
        "Analyze the provided background context material thoroughly (which contains historical ticket records and official technical manuals).\n"
        "Draft a concise, step-by-step troubleshooting path for the user based heavily on the matching files found. "
        "If the solution isn't explicit in the provided context, rely on your deep computing background to give a clear, safe walkthrough."
    )

    # 4. Generate response instantly using Groq (llama-3.3-70b-versatile)
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context Material:\n{context_material}\n\nIncoming Workplace Ticket: {payload.question}"}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.2,
        )
        
        ai_response_text = chat_completion.choices[0].message.content
        return AssistantResponse(answer=ai_response_text, sources_used=referenced_sources)
        
    except Exception as groq_error:
        raise HTTPException(
            status_code=502, 
            detail=f"Groq Inference Engine Exception: {str(groq_error)}"
        )