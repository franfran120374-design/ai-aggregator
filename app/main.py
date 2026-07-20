"""
Agrégateur d'IA intelligent — API principale.

Lancer avec :
    uvicorn app.main:app --reload

Endpoints :
    POST /chat            -> {prompt: str}  =>  réponse + métadonnées de routage
                              (provider + model_id optionnels pour forcer un modèle précis)
    POST /prompt/analyze  -> {prompt: str}  =>  thème détecté + prompt optimisé + diff pédagogique
    POST /youtube/fiche   -> {url: str}     =>  fiche de révision à partir d'une vidéo YouTube
    GET  /models          -> liste des modèles gratuits dispo, groupés par catégorie
    GET  /status          -> état des quotas par provider
"""
import os

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.router import classify_prompt, pick_and_call, call_premium, NoModelAvailable, BudgetExceeded, InvalidModel
from app.team import run_team
from app.quota import status as quota_status
from app.budget import status as budget_status
from app.config import MODELS, CATEGORIES, PROVIDERS, APP_ACCESS_TOKEN
from app.youtube import extract_video_id, fetch_video_title, fetch_transcript, YoutubeError
from app.prompts import build_revision_prompt
from app.prompt_analyzer import analyze_prompt

app = FastAPI(title="Agrégateur IA", version="0.4.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_token(x_access_token: str | None = Header(None)) -> None:
    """Si APP_ACCESS_TOKEN est défini (usage exposé hors machine locale), vérifie le header."""
    if APP_ACCESS_TOKEN and x_access_token != APP_ACCESS_TOKEN:
        raise HTTPException(401, "Code d'accès invalide ou manquant.")


class ChatRequest(BaseModel):
    prompt: str
    category: str | None = None
    provider: str | None = None
    model_id: str | None = None
    premium: bool = False
    premium_provider: str = "anthropic"


class ChatResponse(BaseModel):
    response: str
    category: str
    provider: str
    model: str
    cost_usd: float | None = None


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
        provider, model_id, result = await pick_and_call(
            req.prompt,
            category,
            forced_provider=req.provider,
            forced_model_id=req.model_id,
        )
    except InvalidModel as e:
        raise HTTPException(400, str(e))
    except NoModelAvailable as e:
        raise HTTPException(503, str(e))

    return ChatResponse(response=result, category=category, provider=provider, model=model_id)


# ── /prompt/analyze ───────────────────────────────────────────────────────────

class PromptAnalyzeRequest(BaseModel):
    prompt: str


class PromptAnalyzeResponse(BaseModel):
    theme: str
    theme_label: str
    confidence: float
    source_tier: str
    original: str
    optimized: str
    changes: list[str]
    explanation: str


@app.post("/prompt/analyze", response_model=PromptAnalyzeResponse, dependencies=[Depends(require_token)])
async def prompt_analyze(req: PromptAnalyzeRequest):
    """
    Détecte le thème d'un prompt et propose une version optimisée avec
    la liste des changements — affichée côté front avant envoi pour que
    l'utilisateur apprenne à mieux formuler ses prompts.
    """
    if not req.prompt.strip():
        raise HTTPException(400, "Le prompt est vide.")
    result = await analyze_prompt(req.prompt.strip())
    return PromptAnalyzeResponse(**result)


# ── /youtube/fiche ────────────────────────────────────────────────────────────

class YoutubeFicheRequest(BaseModel):
    url: str
    provider: str | None = None
    model_id: str | None = None


class YoutubeFicheResponse(BaseModel):
    title: str
    video_id: str
    fiche: str
    category: str
    provider: str
    model: str


@app.post("/youtube/fiche", response_model=YoutubeFicheResponse, dependencies=[Depends(require_token)])
async def youtube_fiche(req: YoutubeFicheRequest):
    try:
        video_id = extract_video_id(req.url)
    except YoutubeError as e:
        raise HTTPException(400, str(e))

    title = await fetch_video_title(video_id)

    try:
        transcript = fetch_transcript(video_id)
    except YoutubeError as e:
        raise HTTPException(422, str(e))

    if not transcript.strip():
        raise HTTPException(422, "Transcript vide — rien à résumer.")

    prompt = build_revision_prompt(title, transcript, req.url)

    try:
        provider, model_id, result = await pick_and_call(
            prompt,
            "contexte_long",
            forced_provider=req.provider,
            forced_model_id=req.model_id,
        )
    except InvalidModel as e:
        raise HTTPException(400, str(e))
    except NoModelAvailable as e:
        raise HTTPException(503, str(e))

    return YoutubeFicheResponse(
        title=title,
        video_id=video_id,
        fiche=result,
        category="contexte_long",
        provider=provider,
        model=model_id,
    )


# ── /models ───────────────────────────────────────────────────────────────────

@app.get("/models", dependencies=[Depends(require_token)])
async def list_models():
    return {
        "categories": CATEGORIES,
        "models": [
            {
                "provider": m.provider,
                "model_id": m.model_id,
                "categories": m.categories,
                "priority": m.priority,
            }
            for m in MODELS
            if PROVIDERS[m.provider].is_free
        ],
    }


# ── /team ─────────────────────────────────────────────────────────────────────

class TeamStep(BaseModel):
    step: str
    provider: str
    model: str


class TeamResponse(BaseModel):
    response: str
    plan: str
    draft: str
    steps: list[TeamStep]
    category: str
    cost_usd: float


@app.post("/team", response_model=TeamResponse, dependencies=[Depends(require_token)])
async def team(req: ChatRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "Le prompt est vide.")
    try:
        result = await run_team(req.prompt)
    except NoModelAvailable as e:
        raise HTTPException(503, str(e))
    except BudgetExceeded as e:
        raise HTTPException(402, str(e))
    return TeamResponse(**result)


# ── /status & / ──────────────────────────────────────────────────────────────

@app.get("/status", dependencies=[Depends(require_token)])
async def status():
    return {"quota": quota_status(), "budget": budget_status()}


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
