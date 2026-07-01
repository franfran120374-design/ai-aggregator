"""
Suivi des quotas par provider, pour éviter de taper des 429 évitables
et pour choisir intelligemment le prochain modèle disponible.

Stockage: fichier JSON simple (suffisant pour un usage solo).
Deux fenêtres suivies : minute glissante (RPM) et jour calendaire (RPD).
"""
import json
import os
import time
from datetime import datetime, timezone
from threading import RLock

from app.config import PROVIDERS, QUOTA_FILE

# RLock (réentrant) car status() appelle can_use() en interne tout en tenant déjà le lock
_lock = RLock()


def _load() -> dict:
    if not os.path.exists(QUOTA_FILE):
        return {}
    try:
        with open(QUOTA_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
    with open(QUOTA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def can_use(provider: str) -> bool:
    """Vérifie si le provider a encore du quota (RPM + RPD)."""
    with _lock:
        data = _load()
        entry = data.get(provider, {})
        cfg = PROVIDERS[provider]

        # RPD : compte du jour
        day = _today_key()
        rpd_count = entry.get("day", {}).get(day, 0)
        if rpd_count >= cfg.rpd:
            return False

        # RPM : timestamps des 60 dernières secondes
        now = time.time()
        recent = [t for t in entry.get("minute_ts", []) if now - t < 60]
        if len(recent) >= cfg.rpm:
            return False

        return True


def record_call(provider: str) -> None:
    """Enregistre un appel réussi (ou tenté) pour ce provider."""
    with _lock:
        data = _load()
        entry = data.setdefault(provider, {"day": {}, "minute_ts": []})

        day = _today_key()
        entry["day"][day] = entry["day"].get(day, 0) + 1

        now = time.time()
        entry["minute_ts"] = [t for t in entry.get("minute_ts", []) if now - t < 60]
        entry["minute_ts"].append(now)

        # nettoyage : on ne garde pas les jours trop vieux
        entry["day"] = {d: c for d, c in entry["day"].items() if d >= day[:7]}  # garde le mois courant

        data[provider] = entry
        _save(data)


def status() -> dict:
    """Retourne l'état actuel des quotas pour affichage/debug."""
    with _lock:
        data = _load()
        day = _today_key()
        result = {}
        now = time.time()
        for name, cfg in PROVIDERS.items():
            entry = data.get(name, {})
            rpd_used = entry.get("day", {}).get(day, 0)
            rpm_used = len([t for t in entry.get("minute_ts", []) if now - t < 60])
            result[name] = {
                "rpd_used": rpd_used,
                "rpd_limit": cfg.rpd,
                "rpm_used": rpm_used,
                "rpm_limit": cfg.rpm,
                "available": can_use(name),
            }
        return result
