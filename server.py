from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from weather_rag_poc import run_weather_assistant

app = FastAPI(title="WeatherGPT API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    text: Optional[str] = None

class QueryRequest(BaseModel):
    prompt: str
    persona: Optional[str] = "general"
    history: Optional[List[ChatMessage]] = []

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "WeatherGPT API"}

@app.post("/api/chat")
def chat_endpoint(req: QueryRequest):
    try:
        formatted_history = [item.model_dump() for item in req.history] if req.history else []
        response = run_weather_assistant(
            prompt=req.prompt,
            history=formatted_history,
            persona=req.persona
        )
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)