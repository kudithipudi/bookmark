"""Seed script with ~30 bookmarks covering tech, finance, tools, learning, travel."""
import asyncio
from app.database import init_db, get_db

SEED_BOOKMARKS = [
    ("https://news.ycombinator.com", "Hacker News", "Social news for programmers", "https://news.ycombinator.com/favicon.ico", "tech,news,programming"),
    ("https://github.com", "GitHub", "Where the world builds software", "https://github.com/favicon.ico", "tech,tools,development"),
    ("https://stackoverflow.com", "Stack Overflow", "Where developers learn and share", "https://stackoverflow.com/favicon.ico", "tech,programming,community"),
    ("https://python.org", "Python.org", "The official Python programming language site", "https://www.python.org/favicon.ico", "python,programming,language"),
    ("https://fastapi.tiangolo.com", "FastAPI", "Modern Python web framework for building APIs", "https://fastapi.tiangolo.com/img/favicon.png", "python,web,framework"),
    ("https://tailwindcss.com", "Tailwind CSS", "A utility-first CSS framework", "https://tailwindcss.com/favicons/favicon.ico", "css,frontend,design"),
    ("https://alpinejs.dev", "Alpine.js", "A rugged minimal JavaScript framework", "https://alpinejs.dev/favicon.ico", "javascript,frontend,framework"),
    ("https://sqlite.org", "SQLite", "Small fast self-contained SQL database engine", "https://sqlite.org/favicon.ico", "database,tools,sql"),
    ("https://www.rust-lang.org", "Rust Programming Language", "A language empowering everyone to build reliable software", "https://www.rust-lang.org/favicon.ico", "rust,programming,language"),
    ("https://docs.docker.com", "Docker Documentation", "Container platform documentation", "https://docs.docker.com/favicons/docs@2x.ico", "docker,devops,tools"),
    ("https://kubernetes.io", "Kubernetes", "Production-grade container orchestration", "https://kubernetes.io/images/favicon.png", "kubernetes,devops,infrastructure"),
    ("https://www.terraform.io", "Terraform", "Infrastructure as code tool", "https://www.terraform.io/favicon.ico", "terraform,devops,infrastructure"),
    ("https://www.investopedia.com", "Investopedia", "Financial education and investing dictionary", "https://www.investopedia.com/favicon.ico", "finance,learning,investing"),
    ("https://www.morningstar.com", "Morningstar", "Investment research and portfolio management", "https://www.morningstar.com/favicon.ico", "finance,investing,research"),
    ("https://www.bogleheads.org", "Bogleheads", "Investing advice inspired by Jack Bogle", "https://www.bogleheads.org/favicon.ico", "finance,investing,community"),
    ("https://www.khanacademy.org", "Khan Academy", "Free world-class education for anyone anywhere", "https://www.khanacademy.org/favicon.ico", "learning,education,free"),
    ("https://www.coursera.org", "Coursera", "Online courses from top universities", "https://www.coursera.org/favicon.ico", "learning,education,courses"),
    ("https://www.notion.so", "Notion", "All-in-one workspace for notes and projects", "https://www.notion.so/images/favicon.ico", "tools,productivity,notes"),
    ("https://obsidian.md", "Obsidian", "A second brain knowledge base", "https://obsidian.md/favicon.ico", "tools,notes,knowledge"),
    ("https://linear.app", "Linear", "Streamlined issue tracking for software teams", "https://linear.app/favicon.ico", "tools,productivity,development"),
    ("https://vercel.com", "Vercel", "Develop preview ship web applications", "https://vercel.com/favicon.ico", "hosting,frontend,deployment"),
    ("https://www.cloudflare.com", "Cloudflare", "Web performance and security", "https://www.cloudflare.com/favicon.ico", "infrastructure,security,cdn"),
    ("https://www.lonelyplanet.com", "Lonely Planet", "Travel guides and tips", "https://www.lonelyplanet.com/favicon.ico", "travel,guides,adventure"),
    ("https://www.atlasoscura.com", "Atlas Obscura", "Curious and wondrous travel destinations", "https://www.atlasobscura.com/favicon.ico", "travel,exploration,culture"),
    ("https://www.rome2rio.com", "Rome2Rio", "Discover how to get anywhere", "https://www.rome2rio.com/favicon.ico", "travel,transport,planning"),
    ("https://www.figma.com", "Figma", "Collaborative interface design tool", "https://www.figma.com/favicon.ico", "design,tools,collaboration"),
    ("https://excalidraw.com", "Excalidraw", "Virtual whiteboard for sketching", "https://excalidraw.com/favicon.ico", "design,tools,whiteboard"),
    ("https://regex101.com", "Regex101", "Online regex tester and debugger", "https://regex101.com/favicon.ico", "tools,regex,development"),
    ("https://httpbin.org", "httpbin", "HTTP request and response service", "https://httpbin.org/favicon.ico", "tools,api,testing"),
    ("https://caniuse.com", "Can I use", "Browser compatibility tables for web technologies", "https://caniuse.com/img/favicon-128.png", "frontend,compatibility,reference"),
]


async def seed():
    await init_db()
    db = await get_db()
    for url, title, description, favicon, tags in SEED_BOOKMARKS:
        try:
            await db.execute(
                "INSERT INTO bookmarks (url, title, description, favicon, tags) VALUES (?, ?, ?, ?, ?)",
                (url, title, description, favicon, tags),
            )
        except Exception:
            pass  # skip duplicates
    await db.commit()
    print(f"Seeded {len(SEED_BOOKMARKS)} bookmarks.")
    await db.close()


if __name__ == "__main__":
    asyncio.run(seed())
