# Agrégateur IA

Route chaque prompt vers le meilleur modèle gratuit disponible (Groq, Gemini, OpenRouter),
selon la catégorie détectée et le quota restant.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# remplis GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY (toutes gratuites, sans CB)
```

Clés gratuites :
- Groq : console.groq.com
- Gemini : aistudio.google.com/apikey
- OpenRouter : openrouter.ai/keys

## Lancer

```bash
uvicorn app.main:app --reload
```

## Utiliser

```bash
curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"prompt": "Écris une fonction Python pour trier une liste"}'

curl localhost:8000/status
```

## Structure

- `app/config.py`   : providers, modèles, table de routage par catégorie
- `app/quota.py`    : tracker de quota (RPM/RPD) persisté en JSON
- `app/router.py`   : classification du prompt + sélection du modèle avec fallback
- `app/providers/client.py` : client unifié (tous les providers sont OpenAI-compatible)
- `app/main.py`     : API FastAPI (POST /chat, GET /status)

## Prochaines étapes possibles

- Cache des réponses (prompts identiques)
- Dashboard web simple pour visualiser les quotas en temps réel
- Fallback browser automation (Playwright) pour les modèles sans API gratuite
