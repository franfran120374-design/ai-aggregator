"""
Extraction de transcript YouTube pour générer des fiches de révision.
Aucune clé API requise : oEmbed pour le titre, youtube-transcript-api pour
les sous-titres (manuels ou auto-générés).
"""
import re

import httpx
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


class YoutubeError(Exception):
    pass


def extract_video_id(url: str) -> str:
    match = YOUTUBE_ID_RE.search(url)
    if not match:
        raise YoutubeError(f"Impossible d'extraire l'ID vidéo depuis : {url}")
    return match.group(1)


async def fetch_video_title(video_id: str) -> str:
    """Titre via l'API oEmbed publique de YouTube — pas de clé nécessaire."""
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(oembed_url)
            resp.raise_for_status()
            return resp.json().get("title", "Vidéo sans titre")
    except Exception:
        return "Vidéo sans titre"


def fetch_transcript(video_id: str, languages: list[str] | None = None) -> str:
    """
    Récupère le transcript (sous-titres manuels ou auto-générés) et le
    concatène en texte brut. Essaie français puis anglais par défaut ;
    si seule une autre langue existe et qu'elle est traduisible, traduit en fr.
    """
    languages = languages or ["fr", "fr-FR", "en", "en-US"]
    try:
        # 1.x : YouTubeTranscriptApi s'instancie, plus statique
        api = YouTubeTranscriptApi()
        transcript_list = api.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(languages)
        except NoTranscriptFound:
            transcript = next(iter(transcript_list))
            if transcript.is_translatable:
                transcript = transcript.translate("fr")
        entries = transcript.fetch()
    except TranscriptsDisabled:
        raise YoutubeError("Les sous-titres sont désactivés pour cette vidéo.")
    except VideoUnavailable:
        raise YoutubeError("Vidéo introuvable ou privée.")
    except Exception as e:
        raise YoutubeError(f"Impossible de récupérer le transcript : {e}")

    # 1.x : les snippets sont des objets (entry.text) plus des dicts (entry["text"])
    return " ".join(entry.text for entry in entries if entry.text)
