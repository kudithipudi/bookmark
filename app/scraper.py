import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin


async def fetch_metadata(url: str) -> dict:
    result = {"title": None, "description": None, "favicon": None}

    if not url.startswith(("http://", "https://")):
        return result

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return result

            soup = BeautifulSoup(resp.text, "html.parser")

            title_tag = soup.find("title")
            if title_tag and title_tag.string:
                result["title"] = title_tag.string.strip()

            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                result["description"] = meta_desc["content"].strip()

            base_url = str(resp.url)

            icon_link = soup.find("link", rel=lambda v: v and "icon" in v)
            if icon_link and icon_link.get("href"):
                result["favicon"] = urljoin(base_url, icon_link["href"])
            else:
                result["favicon"] = urljoin(base_url, "/favicon.ico")

    except (httpx.HTTPError, Exception):
        pass

    return result
