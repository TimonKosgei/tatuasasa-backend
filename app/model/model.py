import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from groq import Groq
from supabase_client import supabase
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Ticketing & Support AI Agent (Powered by Groq)")



# 2. Initialize the Gemini Client (Strictly kept for vectorizing text)
try:
    gemini_client = genai.Client()
except Exception as e:
    print(f"Warning: Gemini initialization failed: {e}")
    gemini_client = None

# 3. Initialize the Groq Client (For ultra-fast text inference)
try:
    # Automatically picks up GROQ_API_KEY from environment
    groq_client = Groq()
except Exception as e:
    print(f"Warning: Groq initialization failed: {e}")
    groq_client = None

# ---- Pydantic Schemas ----
class QuestionRequest(BaseModel):
    question: str

class BotResponse(BaseModel):
    answer: str
    sources_used: list[str]

# ---- Embedding Helper (Gemini) ----
def get_embedding(text: str) -> list[float]:
    """Keeps text-embedding-004 for generating 768-dim Supabase vectors."""
    if not gemini_client:
        raise HTTPException(status_code=500, detail="Gemini embedding engine is offline.")
    try:
        response = gemini_client.models.embed_content(
            model="text-embedding-004",
            contents=text
        )
        if isinstance(response.embeddings, list):
            return response.embeddings[0].values
        return response.embedding.values
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failure: {str(e)}")

# ---- Core Ask Endpoint with Groq Integration ----
@app.post("/ask", response_model=BotResponse)
async def ask_bot(request: QuestionRequest):
    if not groq_client:
        raise HTTPException(status_code=500, detail="Groq Inference Engine is offline.")
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
        
    # Convert query text into coordinates vector
    query_vector = get_embedding(request.question)
    
    context_blocks = []
    sources = []
    
    try:
        # Query Stream 1: Official Documentation using Supabase RPC similarity function
        doc_response = supabase.rpc(
            "match_documentation", 
            {"query_embedding": query_vector, "match_threshold": 0.4, "match_count": 2}
        ).execute()
        
        # Query Stream 2: Solved Tickets using your native pgvector column
        ticket_response = supabase.rpc(
            "match_solved_tickets", # Ensure you have a matching RPC function for solved tickets
            {"query_embedding": query_vector, "match_threshold": 0.4, "match_count": 2}
        ).execute()
        
        # Parse match data frames
        if doc_response.data:
            for item in doc_response.data:
                context_blocks.append(f"[Official Guide: {item['title']}]\n{item['content']}")
                sources.append(item['title'])
                
        if ticket_response.data:
            for item in ticket_response.data:
                context_blocks.append(f"[Past Solved Ticket ID: {item['ticket_id']}]\n{item['searchable_text']}")
                sources.append(f"Ticket #{item['ticket_id']}")
                
    except Exception as db_err:
        print(f"Database RPC retrieval warning: {db_err}")
        # Continue executing so the model can still try answering with its generic tech knowledge base

    combined_context = "\n\n---\n\n".join(context_blocks)

    system_instruction = (
        "You are an expert IT support technician tier-1 AI agent. "
        "Use the provided official documentation and past resolved tickets to answer the incoming ticket request. "
        "Prioritize official documentation instructions, but adapt if a past resolved ticket shows a specific updated fix. "
        "If the context doesn't contain the answer, use your pre-existing IT knowledge to give a safe, structured troubleshooting guide."
    )

    # ---- Call Groq API instead of Gemini ----
    try:
        # Standard OpenAI-compatible format used by Groq
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": system_instruction
                },
                {
                    "role": "user",
                    "content": f"Context Material:\n{combined_context}\n\nIncoming Ticket: {request.question}\n\nProvide resolution steps:"
                }
            ],
            # llama-3.3-70b-versatile is highly recommended for reasoning and text generation speed
            model="llama-3.3-70b-versatile",
            temperature=0.2, # Lower temperature forces highly accurate documentation extraction
        )
        
        # Safely extract text string from Groq response schema
        ai_answer = chat_completion.choices[0].message.content
        return BotResponse(answer=ai_answer, sources_used=sources)
        
    except Exception as groq_err:
        raise HTTPException(status_code=502, detail=f"Groq Service Exception: {str(groq_err)}")

@app.get("/")
def read_root():
    return {"status": "Groq-Powered AI Ticketing Backend Active"}