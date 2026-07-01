"""
Configuration centrale de l'agrégateur.
Toutes les clés API viennent des variables d'environnement (voir .env.example).
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    rpm: int
    rpd: int
    tpm: int | None = None  # tokens/minute — None si non publié par le provider
    is_free: bool = True
    # prix par million de tokens (input, output) — uniquement pour les providers payants
    price_per_mtok: tuple[float, float] | None = None


PROVIDERS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        rpm=30,
        rpd=1000,
        tpm=6_000,
    ),
    "gemini": ProviderConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="GEMINI_API_KEY",
        rpm=10,
        rpd=1500,
        tpm=250_000,
    ),
    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        rpm=20,
        rpd=50,  # passe à 1000 si 10$ de crédits achetés une fois
    ),
    # --- Providers payants, jamais choisis automatiquement (voir router.py) ---
    "anthropic": ProviderConfig(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        rpm=50,       # dépend de ton tier réel, ajuste si besoin
        rpd=10_000,   # pas de vraie limite RPD, seul le budget $ compte ici
        is_free=False,
        price_per_mtok=(3.00, 15.00),  # Sonnet 4.6 par défaut
    ),
    "openai": ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        rpm=50,
        rpd=10_000,
        is_free=False,
        price_per_mtok=(2.50, 10.00),  # à ajuster selon le modèle exact utilisé
    ),
}


@dataclass
class ModelConfig:
    provider: str
    model_id: str
    categories: list[str] = field(default_factory=list)  # ce pour quoi il est bon
    priority: int = 1  # 1 = essayer en premier dans sa catégorie


# Table des modèles disponibles, avec leurs forces.
# L'ordre à l'intérieur d'une catégorie = ordre de préférence (priority croissante).
MODELS: list[ModelConfig] = [
    # Rapide / classification / petites tâches
    ModelConfig("groq", "llama-3.1-8b-instant", ["classification", "rapide"], priority=1),

    # Code
    ModelConfig("openrouter", "qwen/qwen3-coder:free", ["code"], priority=1),
    ModelConfig("groq", "llama-3.3-70b-versatile", ["code", "raisonnement"], priority=2),

    # Raisonnement / analyse complexe
    ModelConfig("openrouter", "openai/gpt-oss-120b:free", ["raisonnement"], priority=1),
    ModelConfig("groq", "llama-3.3-70b-versatile", ["raisonnement"], priority=2),

    # Rédaction / créatif
    ModelConfig("groq", "llama-3.3-70b-versatile", ["redaction", "creatif"], priority=1),
    ModelConfig("openrouter", "meta-llama/llama-3.3-70b-instruct:free", ["redaction", "creatif"], priority=2),

    # Contexte long / documents volumineux
    ModelConfig("gemini", "gemini-2.5-flash", ["contexte_long"], priority=1),
    ModelConfig("gemini", "gemini-2.5-flash-lite", ["contexte_long"], priority=2),

    # Généraliste (fallback ultime si tout le reste est à sec)
    ModelConfig("openrouter", "meta-llama/llama-3.3-70b-instruct:free", ["general"], priority=1),
    ModelConfig("gemini", "gemini-2.5-flash-lite", ["general"], priority=2),

    # --- Premium (payant) : jamais sélectionnés par le classifieur automatique.
    # Utilisables uniquement via un appel explicite (voir router.call_premium).
    ModelConfig("anthropic", "claude-sonnet-4-6", ["premium"], priority=1),
    ModelConfig("openai", "gpt-5-mini", ["premium"], priority=2),
]

CATEGORIES = ["classification", "code", "raisonnement", "redaction", "creatif", "contexte_long", "general"]
# catégorie séparée : jamais retournée par classify_local, accessible seulement à la demande
PREMIUM_CATEGORY = "premium"

# Plafond de dépense mensuel en dollars pour les providers payants.
# Modifiable via la variable d'env MAX_MONTHLY_SPEND_USD dans .env
MAX_MONTHLY_SPEND_USD = float(os.environ.get("MAX_MONTHLY_SPEND_USD", "5.0"))


def get_api_key(provider: str) -> str:
    cfg = PROVIDERS[provider]
    key = os.environ.get(cfg.api_key_env)
    if not key:
        raise RuntimeError(
            f"Clé API manquante pour {provider}. Définis {cfg.api_key_env} dans ton .env"
        )
    return key


QUOTA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "quota.json")
