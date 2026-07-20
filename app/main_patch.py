# ════════════════════════════════════════════════════════════════════
# PATCH app/main.py  — deux endroits à modifier
# ════════════════════════════════════════════════════════════════════

# ── 1. Ajouter cet import à la suite des imports existants ────────────────────

from app.prompt_analyzer import analyze_prompt

# ── 2. Coller ce bloc AVANT la dernière ligne (@app.get("/")) ────────────────

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
    la liste des changements apportés — affichée côté front avant envoi
    pour que l'utilisateur comprenne ce qui a changé et pourquoi.
    """
    if not req.prompt.strip():
        raise HTTPException(400, "Le prompt est vide.")
    result = await analyze_prompt(req.prompt.strip())
    return PromptAnalyzeResponse(**result)
