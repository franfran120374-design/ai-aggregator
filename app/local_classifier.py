"""
Classifieur de prompt 100% local (aucun appel réseau, donc 0 consommation
de quota et latence quasi nulle).

Approche : scoring multi-signaux. Chaque catégorie a des indices (regex,
mots-clés, structure du texte) avec un poids. On additionne les points
par catégorie et on prend le maximum. Plus fiable qu'un simple
"premier mot-clé trouvé" parce qu'un prompt peut mentionner plusieurs
signaux à la fois (ex: "corrige le bug dans ce long fichier" = code + contexte_long).
"""
import re

# (regex compilée, poids)
_PATTERNS: dict[str, list[tuple[re.Pattern, int]]] = {
    "code": [
        (re.compile(r"```"), 5),
        (re.compile(r"\b(def|class|import|function|const|let|var)\b"), 3),
        (re.compile(r"\b(bug|debug|erreur|error|traceback|stack ?trace)\b", re.I), 3),
        (re.compile(r"\b(code|script|fonction|algorithme|api|regex|sql|requête sql)\b", re.I), 2),
        (re.compile(r"\.(py|js|ts|java|cpp|go|rs|rb|php|sql)\b", re.I), 3),
        (re.compile(r"\b(compile|syntax|exception|null pointer|segfault)\b", re.I), 2),
    ],
    "raisonnement": [
        (re.compile(r"\b(pourquoi|démontre|prouve|justifie)\b", re.I), 3),
        (re.compile(r"\b(calcule|résous|probabilité|équation|logique)\b", re.I), 3),
        (re.compile(r"\b(compare|évalue|avantages? et inconvénients?|stratégie)\b", re.I), 2),
        (re.compile(r"\b(analyse (les|des|ces)|raisonnement|hypothèse)\b", re.I), 2),
    ],
    "redaction": [
        (re.compile(r"\b(écris|rédige|rédiger) (un |une |le |la )?(email|mail|lettre|article|post|message)\b", re.I), 4),
        (re.compile(r"\b(lettre de motivation|cv|linkedin|newsletter|communiqué)\b", re.I), 3),
        (re.compile(r"\b(résume en|synthèse courte|paragraphe sur)\b", re.I), 2),
    ],
    "creatif": [
        (re.compile(r"\b(histoire|conte|poème|poeme|roman|nouvelle)\b", re.I), 4),
        (re.compile(r"\b(personnage|scénario|dialogue fictif|univers imaginaire)\b", re.I), 3),
        (re.compile(r"\b(raconte[- ]moi|imagine (un|une|que))\b", re.I), 3),
    ],
    "contexte_long": [
        (re.compile(r"\b(résume ce (document|fichier|texte|rapport))\b", re.I), 4),
        (re.compile(r"\b(analyse ce (document|fichier|pdf)|voici le texte)\b", re.I), 3),
        (re.compile(r"\b(rapport long|plusieurs (fichiers|documents)|dossier complet)\b", re.I), 3),
    ],
}

# Au-delà de cette taille, on ajoute des points à "contexte_long"
# (un prompt qui colle 3000+ caractères est probablement un document à traiter)
_LONG_PROMPT_THRESHOLD = 3000
_LONG_PROMPT_BONUS = 4


def classify_local(prompt: str) -> str:
    """Retourne la catégorie avec le meilleur score. 'general' si aucun signal clair."""
    scores: dict[str, int] = {cat: 0 for cat in _PATTERNS}

    for category, patterns in _PATTERNS.items():
        for pattern, weight in patterns:
            matches = len(pattern.findall(prompt))
            if matches:
                # on plafonne l'effet de répétition (3 occurrences max comptées)
                scores[category] += weight * min(matches, 3)

    if len(prompt) > _LONG_PROMPT_THRESHOLD:
        scores["contexte_long"] += _LONG_PROMPT_BONUS

    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]

    # Seuil minimal pour éviter de trancher sur du bruit (1 mot-clé isolé et faible)
    if best_score < 2:
        return "general"

    return best_category
