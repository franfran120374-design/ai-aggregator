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

Puis ouvre `http://127.0.0.1:8000` : interface de chat directement dans le navigateur.

## Accès depuis un autre appareil (téléphone, etc.)

Sur Windows, double-clique `start.bat` : ça lance le serveur **et** un tunnel public
(Cloudflare Tunnel, gratuit, sans compte) dans deux fenêtres séparées. L'URL publique
en `https://....trycloudflare.com` s'affiche dans la fenêtre "Tunnel public" — elle
change à chaque lancement.

Nécessite `tools/cloudflared.exe` (binaire autonome, pas d'installeur) :
https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe

Dès que le serveur est exposé ainsi, définis `APP_ACCESS_TOKEN` dans `.env` (un secret
au choix) : sans ça, n'importe qui avec le lien peut l'utiliser. Le frontend demande
ce code une seule fois et le retient sur l'appareil.

## Utiliser (API directe)

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
