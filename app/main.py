"""
Agrégateur d'IA intelligent — API principale.

Lancer avec :
    uvicorn app.main:app --reload

Endpoints :
    POST /chat    -> {prompt: str}  =>  réponse + métadonnées de routage
    GET  /status  -> état des quotas par provider
"""
import os

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.router import classify_prompt, pick_and_call, call_premium, NoModelAvailable, BudgetExceeded
from app.team import run_team
from app.quota import status as quota_status
from app.budget import status as budget_status
from app.config import PROVIDERS, APP_ACCESS_TOKEN

app = FastAPI(title="Agrégateur IA", version="0.1.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_token(x_access_token: str | None = Header(None)) -> None:
    """Si APP_ACCESS_TOKEN est défini (usage exposé hors machine locale), vérifie le header."""
    if APP_ACCESS_TOKEN and x_access_token != APP_ACCESS_TOKEN:
        raise HTTPException(401, "Code d'accès invalide ou manquant.")


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


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_token)])
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


class TeamStep(BaseModel):
    step: str  # "plan", "execution" ou "relecture"
    provider: str
    model: str


class TeamResponse(BaseModel):
    response: str  # version finale relue
    plan: str
    draft: str
    steps: list[TeamStep]
    category: str
    cost_usd: float  # 0 si tout est passé par le CLI abonnement + les gratuits


@app.post("/team", response_model=TeamResponse, dependencies=[Depends(require_token)])
async def team(req: ChatRequest):
    """
    Mode équipe : Claude planifie, un modèle gratuit exécute, Claude relit.
    Plus lent qu'un /chat simple (3 appels en série) mais nettement meilleur
    sur les tâches complexes (code, documents structurés, analyses).
    """
    if not req.prompt.strip():
        raise HTTPException(400, "Le prompt est vide.")
    try:
        result = await run_team(req.prompt)
    except NoModelAvailable as e:
        raise HTTPException(503, str(e))
    except BudgetExceeded as e:
        raise HTTPException(402, str(e))
    return TeamResponse(**result)


@app.get("/status", dependencies=[Depends(require_token)])
async def status():
    return {"quota": quota_status(), "budget": budget_status()}


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
