"""
Coeur de l'agrégateur :
1. classify_prompt() : un petit modèle rapide tague le prompt (code, redaction, etc.)
2. pick_and_call()   : on prend le meilleur modèle de cette catégorie qui a
                        encore du quota dispo, avec fallback en cascade.
                        Un modèle précis peut aussi être forcé manuellement.
"""
import logging

from app.config import MODELS, ModelConfig, PROVIDERS
from app.providers.client import call_model, ProviderError
from app.quota import can_use, record_call
from app.local_classifier import classify_local
from app.budget import can_afford, record_spend, estimate_cost_usd

logger = logging.getLogger(__name__)


class NoModelAvailable(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class InvalidModel(Exception):
    pass


async def classify_prompt(prompt: str) -> str:
    """Classification locale par règles pondérées — aucun appel réseau, latence ~0."""
    return classify_local(prompt)


def _candidates_for(category: str) -> list[ModelConfig]:
    matches = [m for m in MODELS if category in m.categories]
    if not matches:
        matches = [m for m in MODELS if "general" in m.categories]
    return sorted(matches, key=lambda m: m.priority)


async def _try_forced_model(
    prompt: str, provider: str, model_id: str, estimated_total: int
) -> tuple[str, str, str] | None:
    """
    Essaie le modèle gratuit demandé explicitement par l'utilisateur.
    Renvoie None (et laisse pick_and_call retomber sur la cascade normale) si
    le quota est épuisé ou si l'appel échoue. Lève InvalidModel si le
    provider/modèle demandé n'existe pas ou n'est pas gratuit — ça, c'est une
    erreur de saisie côté appelant, pas une histoire de quota, donc ça remonte.
    """
    if provider not in PROVIDERS or not PROVIDERS[provider].is_free:
        raise InvalidModel(f"'{provider}' n'est pas un provider gratuit valide.")
    if not any(m.provider == provider and m.model_id == model_id for m in MODELS):
        raise InvalidModel(f"Modèle {provider}/{model_id} inconnu (absent de MODELS dans config.py).")

    if not can_use(provider, estimated_tokens=estimated_total):
        logger.info("Quota épuisé pour le modèle forcé %s/%s, bascule sur la cascade normale", provider, model_id)
        return None
    try:
        content, usage = await call_model(provider, model_id, prompt)
        record_call(provider, tokens=usage["input_tokens"] + usage["output_tokens"])
        return provider, model_id, content
    except ProviderError as e:
        logger.warning("Echec du modèle forcé %s/%s: %s, bascule sur la cascade normale", provider, model_id, e)
        return None


async def pick_and_call(
    prompt: str,
    category: str,
    forced_provider: str | None = None,
    forced_model_id: str | None = None,
) -> tuple[str, str, str]:
    """
    Essaie les modèles gratuits de la catégorie dans l'ordre de priorité, en
    sautant ceux dont le quota est épuisé, puis retombe sur les modèles 'general'.
    Ne touche JAMAIS aux providers payants (filtrés explicitement).

    Si forced_provider/forced_model_id sont fournis, ce modèle précis est
    essayé en premier ; en cas de quota épuisé ou d'erreur, on retombe sur la
    cascade normale (comportement "meilleur effort") plutôt que d'échouer.
    Retourne (provider, model_id, réponse).
    """
    estimated_input = len(prompt) // 4
    estimated_total = estimated_input + 500

    if forced_provider and forced_model_id:
        forced_result = await _try_forced_model(prompt, forced_provider, forced_model_id, estimated_total)
        if forced_result is not None:
            return forced_result

    tried = set()
    if forced_provider and forced_model_id:
        tried.add((forced_provider, forced_model_id))

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
            if not can_use(m.provider, estimated_tokens=estimated_total):
                logger.info("Quota local insuffisant pour %s/%s, on saute", m.provider, m.model_id)
                continue
            try:
                content, usage = await call_model(m.provider, m.model_id, prompt)
                record_call(m.provider, tokens=usage["input_tokens"] + usage["output_tokens"])
                return m.provider, m.model_id, content
            except ProviderError as e:
                logger.warning("Echec %s/%s: %s", m.provider, m.model_id, e)
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
