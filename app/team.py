"""
Mode équipe : trois modèles collaborent sur la même demande.

    1. PLAN       — Claude structure la demande en plan d'action précis.
    2. EXÉCUTION  — le meilleur modèle GRATUIT de la catégorie réalise la tâche
                    en suivant le plan (zéro coût).
    3. RELECTURE  — Claude relit le brouillon et produit la version finale corrigée.

Pour les étapes Claude, cascade de moyens (du moins cher au plus cher) :
    CLI Claude Code (abonnement Pro, coût zéro)
    → API Anthropic si ANTHROPIC_API_KEY est définie (budget mensuel vérifié)
    → meilleur modèle gratuit de raisonnement (dégradé mais fonctionnel).
"""
import logging
import os

from app.claude_code import cli_available, generate, ClaudeCodeError
from app.local_classifier import classify_local
from app.providers.client import ProviderError
from app.router import pick_and_call, call_premium, BudgetExceeded, NoModelAvailable

logger = logging.getLogger(__name__)

PLAN_PROMPT = """Tu es l'architecte d'une équipe d'IA. Un autre modèle exécutera la tâche : ton rôle est UNIQUEMENT de planifier, pas de réaliser.

Demande de l'utilisateur :
---
{prompt}
---

Produis un plan d'action clair et compact :
- les étapes numérotées dans l'ordre,
- les exigences et contraintes importantes,
- les pièges à éviter,
- ce à quoi doit ressembler un résultat réussi.

Réponds dans la langue de la demande. Plan uniquement, pas de réalisation."""

EXECUTE_PROMPT = """Tu fais partie d'une équipe d'IA. Un architecte a préparé un plan : ton rôle est de réaliser la tâche COMPLÈTEMENT en le suivant.

Demande de l'utilisateur :
---
{prompt}
---

Plan de l'architecte :
---
{plan}
---

Réalise maintenant la tâche entièrement. Livre le résultat final demandé (code complet, texte complet, etc.), pas un résumé de ce que tu ferais."""

REVIEW_PROMPT = """Tu es le relecteur final d'une équipe d'IA. Un modèle a produit un brouillon : ton rôle est de le vérifier et de livrer la VERSION FINALE.

Demande initiale de l'utilisateur :
---
{prompt}
---

Brouillon produit par l'équipe :
---
{draft}
---

Vérifie que le brouillon répond bien à la demande, corrige les erreurs (bugs, incohérences, oublis, fautes) et améliore la qualité.

IMPORTANT : réponds UNIQUEMENT avec la version finale complète, directement utilisable par l'utilisateur. Pas de commentaires sur le brouillon, pas de liste de corrections, pas de méta-discours."""


async def _call_claude(prompt: str) -> tuple[str, str, str, float]:
    """
    Appelle Claude par le moyen le moins cher disponible.
    Retourne (provider, model, texte, cout_usd).
    """
    if cli_available():
        try:
            text = await generate(prompt)
            return "claude-code", "abonnement Pro", text, 0.0
        except ClaudeCodeError as e:
            logger.warning("CLI Claude Code indisponible (%s), on tente la suite", e)

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            content, usage = await call_premium(prompt, "anthropic", "claude-sonnet-4-6")
            return "anthropic", "claude-sonnet-4-6", content, usage["cost_usd"]
        except (BudgetExceeded, ProviderError) as e:
            logger.warning("API Anthropic indisponible (%s), on retombe sur le gratuit", e)

    provider, model, content = await pick_and_call(prompt, "raisonnement")
    return provider, model, content, 0.0


async def run_team(prompt: str) -> dict:
    """
    Enchaîne plan -> exécution -> relecture et retourne le résultat complet
    avec les métadonnées de chaque étape.
    Peut lever NoModelAvailable si même les modèles gratuits sont à sec.
    """
    category = classify_local(prompt)
    steps = []
    total_cost = 0.0

    # 1. Plan (Claude)
    provider, model, plan, cost = await _call_claude(PLAN_PROMPT.format(prompt=prompt))
    steps.append({"step": "plan", "provider": provider, "model": model})
    total_cost += cost
    logger.info("Équipe/plan via %s (%d caractères)", provider, len(plan))

    # 2. Exécution (meilleur modèle gratuit de la catégorie)
    provider, model, draft = await pick_and_call(
        EXECUTE_PROMPT.format(prompt=prompt, plan=plan), category
    )
    steps.append({"step": "execution", "provider": provider, "model": model})
    logger.info("Équipe/exécution via %s/%s (%d caractères)", provider, model, len(draft))

    # 3. Relecture (Claude) — livre directement la version finale
    provider, model, final, cost = await _call_claude(
        REVIEW_PROMPT.format(prompt=prompt, draft=draft)
    )
    steps.append({"step": "relecture", "provider": provider, "model": model})
    total_cost += cost
    logger.info("Équipe/relecture via %s (%d caractères)", provider, len(final))

    return {
        "response": final,
        "plan": plan,
        "draft": draft,
        "steps": steps,
        "category": category,
        "cost_usd": round(total_cost, 6),
    }
