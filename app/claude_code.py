"""
Appel de Claude via le CLI Claude Code en mode non-interactif (`claude -p`).
L'usage est couvert par l'abonnement Claude Pro/Max de la machine — aucune clé
API ni coût à l'usage, mais ça ne fonctionne que là où le CLI est installé et
connecté (donc pas sur Render).
"""
import asyncio
import logging
import os
import shutil

logger = logging.getLogger(__name__)

# Dossier de travail neutre pour le CLI : évite qu'il considère le code de
# l'agrégateur comme "son projet" pendant une simple génération de texte.
WORKDIR = os.path.join(os.path.dirname(__file__), "..", "data")

TIMEOUT_SECONDS = float(os.environ.get("CLAUDE_CODE_TIMEOUT", "240"))

_cli_path: str | None = None
_disabled = False  # passe à True si le CLI est installé mais pas connecté (/login)


class ClaudeCodeError(Exception):
    pass


def cli_available() -> bool:
    """True si le CLI `claude` est trouvable dans le PATH (résolu une seule fois)."""
    global _cli_path
    if _disabled:
        return False
    if _cli_path is None:
        _cli_path = shutil.which("claude") or ""
        if _cli_path:
            logger.info("CLI Claude Code détecté : %s", _cli_path)
    return bool(_cli_path)


async def generate(prompt: str) -> str:
    """
    Envoie le prompt à `claude -p` (via stdin, pour éviter toute limite de
    longueur de ligne de commande) et retourne la réponse texte.
    """
    if not cli_available():
        raise ClaudeCodeError("CLI claude introuvable dans le PATH.")

    proc = await asyncio.create_subprocess_exec(
        _cli_path,
        "-p",
        "--output-format", "text",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=WORKDIR,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")), timeout=TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise ClaudeCodeError(f"Timeout après {TIMEOUT_SECONDS:.0f}s.")

    if proc.returncode != 0:
        # le CLI écrit parfois son erreur sur stdout (ex: "Not logged in")
        detail = (
            stderr.decode("utf-8", errors="replace").strip()
            or stdout.decode("utf-8", errors="replace").strip()
        )[:500]
        if "not logged in" in detail.lower() or "/login" in detail.lower():
            global _disabled
            _disabled = True
            logger.warning(
                "CLI Claude Code installé mais non connecté — désactivé pour cette session. "
                "Lance `claude` dans un terminal puis tape /login pour l'activer."
            )
        raise ClaudeCodeError(f"claude -p a échoué (code {proc.returncode}): {detail}")

    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        raise ClaudeCodeError("claude -p a renvoyé une réponse vide.")
    return text
