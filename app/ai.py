import httpx
import os

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.0-flash-001"


async def generate_tags(url: str, title: str | None, description: str | None) -> list[str]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return []

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
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            if resp.status_code != 200:
                return []

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            tags = [t.strip().lower() for t in content.split(",") if t.strip()]
            return tags

    except Exception:
        return []
