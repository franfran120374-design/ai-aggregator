"""
Coeur de l'agrégateur :
1. classify_prompt() : un petit modèle rapide tague le prompt (code, redaction, etc.)
2. pick_model()      : on prend le meilleur modèle de cette catégorie qui a
                        encore du quota dispo, avec fallback en cascade.
"""
from app.config import MODELS, ModelConfig, PROVIDERS
from app.providers.client import call_model, ProviderError
from app.quota import can_use, record_call
from app.local_classifier import classify_local
from app.budget import can_afford, record_spend, estimate_cost_usd


class NoModelAvailable(Exception):
    pass


class BudgetExceeded(Exception):
    pass


async def classify_prompt(prompt: str) -> str:
    """Classification locale par règles pondérées — aucun appel réseau, latence ~0."""
    return classify_local(prompt)


def _candidates_for(category: str) -> list[ModelConfig]:
    matches = [m for m in MODELS if category in m.categories]
    if not matches:
        matches = [m for m in MODELS if "general" in m.categories]
    return sorted(matches, key=lambda m: m.priority)


async def pick_and_call(prompt: str, category: str) -> tuple[str, str, str]:
    """
    Essaie les modèles gratuits de la catégorie dans l'ordre de priorité, en
    sautant ceux dont le quota est épuisé, puis retombe sur les modèles 'general'.
    Ne touche JAMAIS aux providers payants (filtrés explicitement).
    Retourne (provider, model_id, réponse).
    """
    tried = set()
    candidate_lists = [_candidates_for(category)]
    if category != "general":
        candidate_lists.append(_candidates_for("general"))

    for candidates in candidate_lists:
        for m in candidates:
            if not PROVIDERS[m.provider].is_free:
                continue  # sécurité : le routage auto ne doit jamais choisir un provider payant
            key = (m.provider, m.model_id)
            if key in tried:
                continue
            tried.add(key)
            if not can_use(m.provider):
                continue
            try:
                content, _usage = await call_model(m.provider, m.model_id, prompt)
                record_call(m.provider)
                return m.provider, m.model_id, content
            except ProviderError:
                continue

    raise NoModelAvailable(
        "Tous les providers gratuits sont soit à quota épuisé, soit en erreur. Réessaie dans une minute."
    )


async def call_premium(prompt: str, provider: str, model_id: str) -> tuple[str, dict]:
    """
    Appel explicite à un provider payant (anthropic/openai). Ne jamais appeler
    automatiquement depuis pick_and_call — uniquement sur demande explicite de l'utilisateur.
    Vérifie le budget mensuel AVANT l'appel (estimation) et enregistre le coût réel APRÈS.
    """
    if PROVIDERS[provider].is_free:
        raise ValueError(f"{provider} est un provider gratuit, utilise pick_and_call à la place.")

    # Estimation grossière avant appel (on affine avec l'usage réel après)
    rough_estimate = estimate_cost_usd(provider, input_tokens=len(prompt) // 4, output_tokens=500)
    if not can_afford(rough_estimate):
        raise BudgetExceeded(
            f"Plafond mensuel atteint pour les providers payants. "
            f"Augmente MAX_MONTHLY_SPEND_USD dans .env si besoin."
        )

    content, usage = await call_model(provider, model_id, prompt)
    real_cost = estimate_cost_usd(provider, usage["input_tokens"], usage["output_tokens"])
    record_spend(real_cost)

    return content, {**usage, "cost_usd": round(real_cost, 6)}
