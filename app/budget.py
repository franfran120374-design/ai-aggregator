"""
Garde-fou financier pour les providers payants (anthropic, openai).
Totalement séparé du quota.py (qui gère RPM/RPD des providers gratuits) —
ici on compte des dollars, pas des requêtes.

Le plafond mensuel est défini dans config.MAX_MONTHLY_SPEND_USD.
Dès qu'il est atteint, can_afford() renvoie False et le router doit refuser
l'appel plutôt que de risquer un dépassement.
"""
import json
import os
from datetime import datetime, timezone
from threading import RLock

from app.config import PROVIDERS, MAX_MONTHLY_SPEND_USD

_lock = RLock()
_BUDGET_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "budget.json")


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load() -> dict:
    if not os.path.exists(_BUDGET_FILE):
        return {}
    try:
        with open(_BUDGET_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(_BUDGET_FILE), exist_ok=True)
    with open(_BUDGET_FILE, "w") as f:
        json.dump(data, f, indent=2)


def estimate_cost_usd(provider: str, input_tokens: int, output_tokens: int) -> float:
    """Estimation du coût d'un appel à partir du nombre de tokens réels (usage renvoyé par l'API)."""
    cfg = PROVIDERS[provider]
    if not cfg.price_per_mtok:
        return 0.0
    price_in, price_out = cfg.price_per_mtok
    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out


def spent_this_month() -> float:
    with _lock:
        data = _load()
        return data.get(_month_key(), 0.0)


def can_afford(estimated_cost: float = 0.0) -> bool:
    """Vérifie qu'ajouter estimated_cost ne dépasse pas le plafond mensuel."""
    with _lock:
        return spent_this_month() + estimated_cost <= MAX_MONTHLY_SPEND_USD


def record_spend(amount_usd: float) -> None:
    with _lock:
        data = _load()
        key = _month_key()
        data[key] = data.get(key, 0.0) + amount_usd
        # on garde seulement le mois courant + précédent, pas la peine d'accumuler
        data = {k: v for k, v in data.items() if k >= key[:4]}  # garde l'année courante
        _save(data)


def status() -> dict:
    with _lock:
        spent = spent_this_month()
        return {
            "spent_this_month_usd": round(spent, 4),
            "monthly_cap_usd": MAX_MONTHLY_SPEND_USD,
            "remaining_usd": round(max(0.0, MAX_MONTHLY_SPEND_USD - spent), 4),
        }
