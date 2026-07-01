"""
Agrégateur d'IA intelligent — API principale.

Lancer avec :
    uvicorn app.main:app --reload

Endpoints :
    POST /chat    -> {prompt: str}  =>  réponse + métadonnées de routage
    GET  /status  -> état des quotas par provider
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.router import classify_prompt, pick_and_call, call_premium, NoModelAvailable, BudgetExceeded
from app.quota import status as quota_status
from app.budget import status as budget_status
from app.config import PROVIDERS

app = FastAPI(title="Agrégateur IA", version="0.1.0")


class ChatRequest(BaseModel):
    prompt: str
    category: str | None = None  # permet de forcer une catégorie manuellement
    premium: bool = False  # active explicitement Claude/GPT (payant)
    premium_provider: str = "anthropic"  # "anthropic" ou "openai"


class ChatResponse(BaseModel):
    response: str
    category: str
    provider: str
    model: str
    cost_usd: float | None = None  # renseigné uniquement si premium=True


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "Le prompt est vide.")

    if req.premium:
        if req.premium_provider not in PROVIDERS or PROVIDERS[req.premium_provider].is_free:
            raise HTTPException(400, "premium_provider doit être 'anthropic' ou 'openai'.")
        model_id = "claude-sonnet-4-6" if req.premium_provider == "anthropic" else "gpt-5-mini"
        try:
            content, usage = await call_premium(req.prompt, req.premium_provider, model_id)
        except BudgetExceeded as e:
            raise HTTPException(402, str(e))
        return ChatResponse(
            response=content,
            category="premium",
            provider=req.premium_provider,
            model=model_id,
            cost_usd=usage["cost_usd"],
        )

    category = req.category or await classify_prompt(req.prompt)

    try:
        provider, model_id, result = await pick_and_call(req.prompt, category)
    except NoModelAvailable as e:
        raise HTTPException(503, str(e))

    return ChatResponse(response=result, category=category, provider=provider, model=model_id)


@app.get("/status")
async def status():
    return {"quota": quota_status(), "budget": budget_status()}


@app.get("/")
async def root():
    return {"message": "Agrégateur IA en ligne. POST /chat, GET /status."}
