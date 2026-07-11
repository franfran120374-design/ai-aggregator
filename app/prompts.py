"""
Construction du prompt pour transformer un transcript YouTube en fiche de
révision structurée.
"""

MAX_TRANSCRIPT_CHARS = 40_000  # gemini-2.5-flash tient large, mais on garde un plafond raisonnable


def build_revision_prompt(title: str, transcript: str, url: str) -> str:
    truncated = transcript[:MAX_TRANSCRIPT_CHARS]
    was_truncated = len(transcript) > MAX_TRANSCRIPT_CHARS

    return f"""Tu es un professeur qui prépare une fiche de révision claire et efficace \
à partir de la transcription d'une vidéo pédagogique. Réponds STRICTEMENT dans ce \
format markdown, sans rien ajouter avant ou après :

## Résumé express
(3-4 phrases : de quoi parle la vidéo et ce qu'on doit en retenir.)

## Plan de la vidéo
(Liste à puces des grandes parties abordées, dans l'ordre, avec 1 ligne de description chacune.)

## Notions clés
(Pour chaque notion importante : **Nom de la notion** — définition claire en 1-2 phrases. \
5 à 10 notions selon la densité du contenu.)

## Questions de révision
(5 à 8 questions ouvertes qui couvrent l'ensemble du contenu, chacune suivie de sa réponse \
courte. Format : **Q :** ... / **R :** ...)

## Quiz rapide
(5 questions à choix multiples (3-4 options chacune) pour s'auto-tester, avec la bonne \
réponse indiquée à la fin de chaque question entre parenthèses.)

## Mots-clés
(6 à 10 mots-clés séparés par des virgules, en minuscules.)

---
Titre de la vidéo : {title}
URL : {url}
{"(Transcript tronqué à " + str(MAX_TRANSCRIPT_CHARS) + " caractères — vidéo longue.)" if was_truncated else ""}
Transcript : {truncated}"""
