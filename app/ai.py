import httpx
import os
from app.logging_config import get_logger

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"

logger = get_logger("ai")


async def generate_tags(url: str, title: str | None, description: str | None) -> list[str]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.debug("OPENROUTER_API_KEY not set; skipping AI tagging for %s", url)
        return []

    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)

    prompt = (
        f"Given this webpage:\nURL: {url}\nTitle: {title or 'N/A'}\n"
        f"Description: {description or 'N/A'}\n\n"
        "Suggest 3-5 short, lowercase tags (single words or hyphenated) that categorize this page. "
        "Return only the tags separated by commas, nothing else."
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            if resp.status_code != 200:
                logger.warning(
                    "OpenRouter (model=%s) returned status %d for %s: %s",
                    model,
                    resp.status_code,
                    url,
                    resp.text[:200],
                )
                return []

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            tags = [t.strip().lower() for t in content.split(",") if t.strip()]
            logger.info("Generated %d tags for %s", len(tags), url)
            return tags

    except Exception as exc:
        logger.warning("AI tagging failed for %s: %s", url, exc)
        return []
