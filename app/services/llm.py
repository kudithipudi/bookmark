import logging
import time

import httpx

from app.config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

logger = logging.getLogger(__name__)

# One pooled client for the worker's lifetime (standards §8): a fresh client per
# call paid a new TCP + TLS handshake every time.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def generate_tags(url: str, title: str | None, description: str | None) -> list[str]:
    api_key = settings.openrouter_api_key
    if not api_key:
        logger.debug("OPENROUTER_API_KEY not set; skipping AI tagging for %s", url)
        return []

    model = settings.openrouter_model
    purpose = "tags"

    prompt = (
        f"Given this webpage:\nURL: {url}\nTitle: {title or 'N/A'}\n"
        f"Description: {description or 'N/A'}\n\n"
        "Suggest 3-5 short, lowercase tags (single words or hyphenated) that categorize this page. "
        "Return only the tags separated by commas, nothing else."
    )

    started = time.perf_counter()
    try:
        resp = await _get_client().post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "usage": {"include": True},
            },
        )

        if resp.status_code != 200:
            logger.error(
                "LLM %s %s failed after %.1fs: status %d for %s: %s",
                purpose,
                model,
                time.perf_counter() - started,
                resp.status_code,
                url,
                resp.text[:200],
            )
            return []

        data = resp.json()
        usage = data.get("usage") or {}
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        logger.info(
            "LLM %s %s %.1fs in=%s out=%s%s",
            purpose,
            model,
            time.perf_counter() - started,
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
            f" reasoning={reasoning}" if reasoning else "",
        )
        content = data["choices"][0]["message"]["content"]
        tags = [t.strip().lower() for t in content.split(",") if t.strip()]
        logger.info("Generated %d tags for %s", len(tags), url)
        return tags

    except Exception as exc:
        logger.error(
            "LLM %s %s failed after %.1fs for %s: %s",
            purpose, model, time.perf_counter() - started, url, exc,
        )
        return []
