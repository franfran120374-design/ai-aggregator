"""
Analyseur de prompt hybride : Tier-1 regex + Tier-2 Groq (détection + optimisation).
Un seul appel Groq pour tout faire — pas de dépendances ajoutées.
Réutilise app.providers.client déjà en place.
"""
import json
import re
import logging
from typing import TypedDict

from app.providers.client import call_model

logger = logging.getLogger(__name__)

# ── Thèmes & patterns ────────────────────────────────────────────────────────

THEMES: dict[str, dict] = {
    "code": {
        "label": "Code / Dev",
        "patterns": [
            r"\bdef \b", r"\bfunction\b", r"\bclass \b", r"\bimport \b",
            r"\bscript\b", r"\bdebug\b", r"\bbug\b", r"\brefactor\b",
            r"\bpython\b", r"\bjavascript\b", r"\btypescript\b", r"\breact\b",
            r"\bfastapi\b", r"\bsql\b", r"\bapi\b", r"\bunit.?test\b",
            r"\bcomplexité\b", r"\balgorithm\b", r"\bcompile\b",
        ],
    },
    "rédaction": {
        "label": "Rédaction",
        "patterns": [
            r"\brédige\b", r"\bécris\b", r"\barticle\b", r"\bessai\b",
            r"\blettre\b", r"\bemail\b", r"\bblog\b", r"\btexte\b",
            r"\bparagraphe\b", r"\bdraft\b", r"\bstyle\b", r"\btone\b",
            r"\bhistoire\b", r"\broman\b", r"\bpoème\b",
        ],
    },
    "analyse": {
        "label": "Analyse",
        "patterns": [
            r"\banalyse\b", r"\banalyze\b", r"\bcompare\b", r"\bévalue\b",
            r"\bsynth[eè]se\b", r"\bcritique\b", r"\binsights?\b",
            r"\btendance\b", r"\bbenchmark\b", r"\bpros?\b.*\bcons?\b",
            r"\bavantages?\b", r"\binconvénients?\b", r"\bswot\b",
        ],
    },
    "math": {
        "label": "Math / Logique",
        "patterns": [
            r"\bcalcule\b", r"\béquation\b", r"\bsolve\b", r"\bprob[aà]bilit\b",
            r"\balg[eè]bre\b", r"\bstatistique\b", r"\bd[eé]montr\b",
            r"\bmatrice\b", r"\bint[eé]grale\b", r"\bd[eé]riv[eé]e?\b",
        ],
    },
}

THRESHOLD = 0.20  # score minimum Tier-1 pour valider sans passer au Tier-2

# ── Méta-prompt Groq ─────────────────────────────────────────────────────────

_META = (
    "Tu es un expert en prompt engineering pédagogique. "
    "Analyse le prompt utilisateur, identifie son thème, réécris-le de façon optimisée "
    "en appliquant les bonnes pratiques (contexte/rôle, format de sortie précis, "
    "contraintes négatives explicites, exemples si utile). "
    "Retourne UNIQUEMENT un objet JSON valide sans aucun texte avant ou après :\n"
    '{"theme":"code|rédaction|analyse|math|général",'
    '"optimized":"prompt réécrit et amélioré",'
    '"changes":["explication courte du changement 1","changement 2","..."],'
    '"explanation":"1-2 phrases sur pourquoi ces changements rendent le prompt plus efficace"}'
)


# ── Tier-1 : regex ────────────────────────────────────────────────────────────

def _tier1(prompt: str) -> tuple[str | None, float]:
    text = prompt.lower()
    best, best_score = None, 0.0
    for tid, t in THEMES.items():
        hits = sum(1 for p in t["patterns"] if re.search(p, text, re.IGNORECASE))
        score = hits / len(t["patterns"])
        if score > best_score:
            best, best_score = tid, score
    if best and best_score >= THRESHOLD:
        return best, round(best_score, 2)
    return None, round(best_score, 2)


# ── Tier-2 : Groq (détection + optimisation en un seul appel) ────────────────

async def _groq_analyze(prompt: str) -> dict:
    full_prompt = f"{_META}\n\n---\nPrompt à analyser :\n{prompt}"
    content, _ = await call_model("groq", "llama-3.1-8b-instant", full_prompt)

    # Extraire le JSON même si Groq ajoute du bruit autour
    start = content.find("{")
    end = content.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"Réponse non-JSON : {content[:300]}")

    return json.loads(content[start:end])


# ── Type de retour public ─────────────────────────────────────────────────────

class AnalysisResult(TypedDict):
    theme: str
    theme_label: str
    confidence: float
    source_tier: str
    original: str
    optimized: str
    changes: list[str]
    explanation: str


# ── Point d'entrée ────────────────────────────────────────────────────────────

async def analyze_prompt(prompt: str) -> AnalysisResult:
    """
    Pipeline hybride :
    - Tier-1 (regex, ~0ms) détecte le thème si score suffisant
    - Tier-2 (Groq llama-3.1-8b-instant) détecte + optimise en un seul appel

    Tier-1 sert uniquement à éviter un appel Groq superflu sur les cas évidents.
    L'optimisation passe toujours par Groq pour la qualité pédagogique.
    """
    theme_id, confidence = _tier1(prompt)
    source = "tier1"

    try:
        groq_data = await _groq_analyze(prompt)
    except Exception as e:
        logger.warning("Groq analyze échoué : %s", e)
        groq_data = {
            "theme": theme_id or "général",
            "optimized": prompt,
            "changes": [],
            "explanation": "Service d'optimisation temporairement indisponible.",
        }

    # Si Tier-1 n'a pas détecté, on prend le thème retourné par Groq
    if theme_id is None:
        source = "tier2"
        theme_id = groq_data.get("theme", "général")
        confidence = 0.65

    return AnalysisResult(
        theme=theme_id,
        theme_label=THEMES.get(theme_id, {}).get("label", theme_id.capitalize()),
        confidence=confidence,
        source_tier=source,
        original=prompt,
        optimized=groq_data.get("optimized", prompt),
        changes=groq_data.get("changes", []),
        explanation=groq_data.get("explanation", ""),
    )
