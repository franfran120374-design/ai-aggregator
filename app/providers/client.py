"""
Client unifié : Groq, Gemini et OpenRouter parlent tous le protocole
OpenAI-compatible (/chat/completions). Un seul client suffit, on change
juste base_url + api_key + model selon le provider choisi par le router.
"""
import httpx

from app.config import PROVIDERS, get_api_key

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class ProviderError(Exception):
    def __init__(self, provider: str, status_code: int, detail: str):
        self.provider = provider
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{provider}] HTTP {status_code}: {detail}")


async def call_model(
    provider: str, model_id: str, prompt: str, system: str | None = None
) -> tuple[str, dict]:
    """
    Appelle un modèle via l'API OpenAI-compatible du provider donné.
    Retourne (contenu_texte, usage) où usage = {"input_tokens": int, "output_tokens": int}.
    """
    cfg = PROVIDERS[provider]
    api_key = get_api_key(provider)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_id, "messages": messages}
    # Anthropic exige max_tokens explicitement via sa couche de compat OpenAI
    if provider == "anthropic":
        payload["max_tokens"] = 4096

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        raise ProviderError(provider, resp.status_code, resp.text[:500])

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    raw_usage = data.get("usage", {})
    usage = {
        "input_tokens": raw_usage.get("prompt_tokens", 0),
        "output_tokens": raw_usage.get("completion_tokens", 0),
    }
    return content, usage
