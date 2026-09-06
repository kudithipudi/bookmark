# Semantic Visuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two SVG visualizations that make the app's embedding features visible — a "match constellation" above search's *Related by meaning* section, and a "collection map" (2D PCA projection of every bookmark embedding) on the analytics page.

**Architecture:** Feature B adds one numpy helper (`SemanticIndex.project_2d`) and one lazy-loaded JSON route (`/api/analytics/map`); its panel is drawn client-side as an SVG string via Alpine `x-html` (the pattern the analytics timeline already uses). Feature A needs no backend — `score` is already serialized per semantic result; the banner is another `x-html` SVG string in the existing Alpine component, with a shared `hoveredId` linking each result card to its star. All motion is `transform`/`opacity` only and is already covered by the global `prefers-reduced-motion` rule in `style.css`.

**Tech Stack:** FastAPI, aiosqlite, numpy 2.5.2 (already in the venv), Alpine.js 3.14 (CDN), Tailwind utility classes (prebuilt `css/app.css`), pytest + pytest-asyncio + httpx AsyncClient.

**Spec:** `docs/superpowers/specs/2026-09-06-semantic-visuals-design.md`

## Global Constraints

- **No new Python dependency.** Projection uses `numpy` only (`import numpy as np`), already imported by `app/services/semantic_index.py`.
- **No new JS dependency / no build step.** Inline SVG built as a markup string and injected with Alpine `x-html` — Alpine `<template x-for>` cloning breaks inside `<svg>` (see the comment at `app/static/analytics.js:56`).
- **Motion:** animate `transform`/`opacity`/`stroke-opacity` only; never `transition: all`. `transform-box: fill-box; transform-origin: center` on any animated SVG shape. Do **not** add a `@media (prefers-reduced-motion)` block — `app/static/style.css:10` already forces `animation-duration`/`transition-duration` to `0.01ms` on `*`.
- **Accessibility:** the constellation `<svg>` is `aria-hidden="true"` (decorative); the collection-map `<svg>` is `role="img"` with an `:aria-label`. The result cards' `% match` bars and the analytics tag/domain lists remain the textual equivalents.
- **Touch:** `touch-action: manipulation` on any new interactive SVG; no `<a>`-wrapped dots (a mistap must not navigate); collection-map dots carry a transparent `r="12"` hit circle; the map callout is a full-width bottom bar below the `sm` breakpoint. Page zoom stays enabled (no `user-scalable=no`).
- **Palette (collection map, in this order):** `#6366f1 #14b8a6 #f59e0b #f43f5e #0ea5e9 #8b5cf6 #10b981 #f97316`; "other"/untagged = `#94a3b8`.
- **Cache-bust:** bump `?v=` on any static file whose contents change, in every template that references it.
- **Commits:** end every commit message with the two trailer lines used on this branch:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0173bhWBotGAwX6Scwbtn3Gt
  ```
- **Test runner:** `./venv/bin/python -m pytest` from `/var/www/bookmark`. Async tests need no decorator (pytest-asyncio auto mode is on).
- Work happens on the existing `semantic-visuals` branch.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `app/services/semantic_index.py` | add `project_2d()` — PCA of the in-memory embedding matrix to `[0,1]²` | 1 |
| `tests/test_semantic.py` | unit tests for `project_2d()` | 1 |
| `app/main.py` | add `GET /api/analytics/map` route | 2 |
| `tests/test_api.py` | endpoint contract + template-markup regression tests | 2, 5 |
| `app/static/analytics.js` | `map` state, IntersectionObserver lazy-load, palette, `galaxySvg` getter, hover/click/escape handlers, callout data | 3 |
| `app/templates/analytics.html` | collection-map panel markup (legend, SVG, callout, states) | 3 |
| `app/static/app.js` | `hoveredId` state, `constellationSvg` getter, `starLabel`, `scrollCardIntoView`, star hover/click handlers | 4 |
| `app/templates/index.html` | constellation banner SVG; card `:id` + hover/focus handlers + ring | 4 |
| `app/static/style.css` | `.star-*` rules; `.galaxy-*` rules; `touch-action` on `.galaxy-svg` | 3, 4 |
| `app/templates/{index,analytics}.html` | `?v=` bumps | 5 |

---

## Task 1: `SemanticIndex.project_2d()`

**Files:**
- Modify: `app/services/semantic_index.py` (add a method to `class SemanticIndex`, after `search`, ends at `:97`)
- Test: `tests/test_semantic.py` (add a new section after the "index ranking" tests, ~`:96`)

**Interfaces:**
- Consumes: `self._matrix` (`np.ndarray | None`, rows L2-normalized, shape `(n, 384)`), `self._ids` (`list[int]`, parallel to matrix rows). Both are populated by `refresh()`.
- Produces: `SemanticIndex.project_2d(self) -> list[tuple[int, float, float]]` — `(bookmark_id, x, y)` per embedding, `x`/`y` in `[0.0, 1.0]` rounded to 4 dp, same order as `self._ids`. Returns `[]` when fewer than 3 embeddings are loaded.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_semantic.py` (the file already has `import numpy as np` and imports `EMBEDDING_DIM, SemanticIndex, decode_embedding`):

```python
# --- unit: 2D projection for the collection map -------------------------


def _loaded_index(*blobs) -> SemanticIndex:
    """A SemanticIndex with its matrix populated directly (no DB), mirroring
    what refresh() does: stack, L2-normalize rows, ids are 1..n."""
    index = SemanticIndex()
    vectors = [decode_embedding(b) for b in blobs]
    matrix = np.vstack(vectors).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    index._matrix = matrix / np.where(norms == 0, 1.0, norms)
    index._ids = list(range(1, len(blobs) + 1))
    return index


def test_project_2d_empty_when_fewer_than_three():
    assert SemanticIndex().project_2d() == []
    assert _loaded_index(make_vector(1.0)).project_2d() == []
    assert _loaded_index(make_vector(1.0), make_vector(0.0, 1.0)).project_2d() == []


def test_project_2d_shape_range_and_order():
    index = _loaded_index(
        make_vector(1.0),
        make_vector(0.0, 1.0),
        make_vector(0.0, 0.0, 1.0),
        make_vector(0.5, 0.5, 0.0, 0.3),
    )
    out = index.project_2d()

    assert [row[0] for row in out] == [1, 2, 3, 4]
    assert len(out) == 4
    for _, x, y in out:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0
    # min-max scaling puts at least one point at each extreme on each axis
    assert min(x for _, x, _ in out) == 0.0
    assert max(x for _, x, _ in out) == 1.0


def test_project_2d_is_deterministic():
    blobs = [make_vector(1.0), make_vector(0.0, 1.0), make_vector(1.0, 1.0),
             make_vector(0.2, 0.9)]
    assert _loaded_index(*blobs).project_2d() == _loaded_index(*blobs).project_2d()


def test_project_2d_degenerate_identical_rows_center_at_half():
    out = _loaded_index(make_vector(1.0), make_vector(1.0), make_vector(1.0)).project_2d()
    assert out == [(1, 0.5, 0.5), (2, 0.5, 0.5), (3, 0.5, 0.5)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_semantic.py -k project_2d -v`
Expected: FAIL — `AttributeError: 'SemanticIndex' object has no attribute 'project_2d'`

- [ ] **Step 3: Implement `project_2d`**

In `app/services/semantic_index.py`, add this method to `class SemanticIndex` immediately after the `search` method (before the module-level `def invalidate_index`):

```python
    def project_2d(self) -> list[tuple[int, float, float]]:
        """(bookmark_id, x, y) for every loaded embedding, projected to 2D
        with PCA (top two principal components) and each axis min-max scaled
        to [0, 1]. Same order as self._ids.

        Returns [] when fewer than 3 embeddings are loaded: PCA on one or two
        points carries no structure, and the caller shows an empty state.
        The caller is responsible for freshness (see search()).
        """
        if self._matrix is None or self._matrix.shape[0] < 3:
            return []

        centered = self._matrix - self._matrix.mean(axis=0, keepdims=True)
        # SVD of the centered matrix is PCA. full_matrices=False keeps U at
        # (n, min(n, dim)); we take the first two components.
        u, s, _ = np.linalg.svd(centered, full_matrices=False)
        coords = u[:, :2] * s[:2]  # (n, 2)

        def scale(column: np.ndarray) -> np.ndarray:
            low = float(column.min())
            high = float(column.max())
            if high - low < 1e-12:
                return np.full(column.shape, 0.5, dtype=np.float64)
            return (column - low) / (high - low)

        xs = scale(coords[:, 0])
        ys = scale(coords[:, 1])
        return [
            (int(bid), round(float(px), 4), round(float(py), 4))
            for bid, px, py in zip(self._ids, xs, ys)
        ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_semantic.py -k project_2d -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full semantic suite to check for regressions**

Run: `./venv/bin/python -m pytest tests/test_semantic.py -v`
Expected: PASS (all pre-existing tests still green)

- [ ] **Step 6: Commit**

```bash
git add app/services/semantic_index.py tests/test_semantic.py
git commit -m "feat: SemanticIndex.project_2d — PCA of embeddings to 2D for the collection map

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0173bhWBotGAwX6Scwbtn3Gt"
```

---

## Task 2: `GET /api/analytics/map` route

**Files:**
- Modify: `app/main.py` — add a route immediately after `get_analytics` (which ends at `:576`). `Counter`, `urlparse`, `get_semantic_index` are already imported (`:5`, `:8`, `:23`).
- Test: `tests/test_api.py` — add after `test_get_analytics` (`:185`). Needs a new `import numpy as np` and a local embedding helper.

**Interfaces:**
- Consumes: `SemanticIndex.project_2d()` from Task 1; `index.is_stale` (property) and `await index.refresh(db)` (mirrors `search`).
- Produces: `GET /api/analytics/map` → JSON
  `{"points": [{"id": int, "x": float, "y": float, "title": str, "domain": str, "url": str, "tag": str | None}], "clusters": [{"tag": str, "count": int}]}`.
  `points` is `[]` and `clusters` is `[]` when fewer than 3 bookmarks have embeddings. `clusters` holds at most the 8 most common non-null first-tags.

- [ ] **Step 1: Write the failing tests**

At the top of `tests/test_api.py`, add below `from unittest.mock import patch`:

```python
import numpy as np

from app.services.semantic_index import EMBEDDING_DIM
```

Then add a helper and tests after `test_get_analytics`:

```python
def _emb(*weights) -> bytes:
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    for i, w in enumerate(weights):
        vec[i] = w
    return vec.tobytes()


async def _add(db, url, title, tags, embedding):
    await db.execute(
        "INSERT INTO bookmarks (url, title, tags, embedding) VALUES (?, ?, ?, ?)",
        (url, title, tags, embedding),
    )
    await db.commit()


async def test_analytics_map_empty(client):
    resp = await client.get("/api/analytics/map")
    assert resp.status_code == 200
    assert resp.json() == {"points": [], "clusters": []}


async def test_analytics_map_below_three_embeddings(client, db):
    await _add(db, "https://a.com", "A", "x", _emb(1.0))
    await _add(db, "https://b.com", "B", "y", _emb(0.0, 1.0))
    resp = await client.get("/api/analytics/map")
    assert resp.status_code == 200
    assert resp.json() == {"points": [], "clusters": []}


async def test_analytics_map_projects_points_and_clusters(client, db):
    await _add(db, "https://a.com", "Alpha", "ml", _emb(1.0))
    await _add(db, "https://www.b.com", "Beta", "ml", _emb(0.0, 1.0))
    await _add(db, "https://c.com", "Gamma", "cooking", _emb(0.0, 0.0, 1.0))
    await _add(db, "https://d.com", "Delta", "", _emb(0.3, 0.2, 0.1, 0.4))

    resp = await client.get("/api/analytics/map")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["points"]) == 4
    for point in data["points"]:
        assert set(point) == {"id", "x", "y", "title", "domain", "url", "tag"}
        assert 0.0 <= point["x"] <= 1.0
        assert 0.0 <= point["y"] <= 1.0

    by_title = {p["title"]: p for p in data["points"]}
    assert by_title["Beta"]["domain"] == "b.com"  # www. stripped
    assert by_title["Delta"]["tag"] is None       # empty tags -> None

    assert data["clusters"] == [
        {"tag": "ml", "count": 2},
        {"tag": "cooking", "count": 1},
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_api.py -k analytics_map -v`
Expected: FAIL — `404` responses (route not defined) / `KeyError`.

- [ ] **Step 3: Implement the route**

In `app/main.py`, directly after the `get_analytics` function (after its closing `}` at `:576`), add:

```python
@app.get("/api/analytics/map")
async def get_analytics_map(request: Request):
    """2D PCA projection of every bookmark embedding, for the analytics
    'Collection map'. Lazy-loaded by the page after first paint, so the SVD
    cost never blocks the KPI row."""
    db = request.app.state.db
    index = await get_semantic_index(request.app.state)
    if index.is_stale:
        await index.refresh(db)

    coords = index.project_2d()
    if not coords:
        return {"points": [], "clusters": []}

    position = {bid: (px, py) for bid, px, py in coords}
    placeholders = ",".join("?" * len(position))
    cursor = await db.execute(
        f"SELECT id, title, url, tags FROM bookmarks WHERE id IN ({placeholders})",
        list(position),
    )

    points = []
    tag_counts = Counter()
    for row in await cursor.fetchall():
        px, py = position[row["id"]]
        first_tag = next(
            (t.strip() for t in (row["tags"] or "").split(",") if t.strip()),
            None,
        )
        host = (urlparse(row["url"]).hostname or "").removeprefix("www.")
        points.append(
            {
                "id": row["id"],
                "x": px,
                "y": py,
                "title": row["title"] or row["url"],
                "domain": host,
                "url": row["url"],
                "tag": first_tag,
            }
        )
        if first_tag is not None:
            tag_counts[first_tag] += 1

    clusters = [
        {"tag": tag, "count": count}
        for tag, count in tag_counts.most_common(8)
    ]
    return {"points": points, "clusters": clusters}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_api.py -k analytics_map -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full API + semantic suites**

Run: `./venv/bin/python -m pytest tests/test_api.py tests/test_semantic.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: GET /api/analytics/map — 2D embedding projection for the collection map

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0173bhWBotGAwX6Scwbtn3Gt"
```

---

## Task 3: Collection-map panel (analytics page)

**Files:**
- Modify: `app/static/analytics.js` — add state + methods to the `analyticsApp` Alpine component (object literal spans `:2`–`:115`).
- Modify: `app/templates/analytics.html` — insert a panel between "Bookmarks over time" (`</div>` at `:100`) and "Top tags + top domains" (`:103`).
- Modify: `app/static/style.css` — append `.galaxy-*` rules (file ends at `:74`).

**Interfaces:**
- Consumes: `GET /api/analytics/map` from Task 2.
- Produces (Alpine component surface used by the template): `map` object, `galaxySvg` getter, `selectedPoint` getter, `galaxyInteractive` getter, `tagColor(tag)`, `onGalaxyHover($event)`, `onGalaxyClick($event)`, `toggleTagFilter(tag)`.

- [ ] **Step 1: Add `map` state and lazy-load to `analytics.js`**

In the component object, add after `hoverIndex: null,` (`:8`):

```javascript
        // Collection map (semantic galaxy): lazily fetched when the panel
        // scrolls near the viewport. `selectedId` drives both mouse-hover
        // and touch-tap — there is no separate hover state.
        map: {
            points: [], clusters: [],
            loaded: false, error: false,
            selectedId: null, tagFilter: null,
        },
```

In `init()`, replace the final line `this.loading = false;` (`:31`) with:

```javascript
            this.loading = false;
            this.$nextTick(() => this.observeMap());
```

Add these methods after `init()` (before `get maxTimelineCount()` at `:34`):

```javascript
        observeMap() {
            const el = this.$refs.mapPanel;
            if (!el || !('IntersectionObserver' in window)) {
                this.loadMap();
                return;
            }
            const obs = new IntersectionObserver((entries) => {
                if (entries.some(e => e.isIntersecting)) {
                    obs.disconnect();
                    this.loadMap();
                }
            }, { rootMargin: '200px' });
            obs.observe(el);
        },

        async loadMap() {
            try {
                const resp = await fetch('api/analytics/map');
                const data = await resp.json();
                this.map.points = data.points || [];
                this.map.clusters = data.clusters || [];
            } catch (e) {
                this.map.error = true;
            }
            this.map.loaded = true;
        },
```

- [ ] **Step 2: Add palette, projection, and SVG-string helpers to `analytics.js`**

Add after `loadMap()`:

```javascript
        galaxyPalette: [
            '#6366f1', '#14b8a6', '#f59e0b', '#f43f5e',
            '#0ea5e9', '#8b5cf6', '#10b981', '#f97316',
        ],

        tagColor(tag) {
            const i = this.map.clusters.findIndex(c => c.tag === tag);
            return (i >= 0 && i < 8) ? this.galaxyPalette[i] : '#94a3b8';
        },

        // viewBox 0 0 460 320, 16px inner padding; y is flipped so higher
        // projected values sit toward the top.
        galaxyX(x) { return 16 + x * (460 - 32); },
        galaxyY(y) { return (320 - 16) - y * (320 - 32); },

        // Beyond this many dots, drop per-point hit targets + interaction and
        // just render the scatter (see the spec's >800 fallback).
        get galaxyInteractive() { return this.map.points.length <= 800; },

        get selectedPoint() {
            return this.map.points.find(p => p.id === this.map.selectedId) || null;
        },

        // Which tag, if any, everything should be dimmed against right now.
        get galaxyActiveTag() {
            if (this.map.selectedId !== null) {
                const p = this.selectedPoint;
                return p ? p.tag : null;
            }
            return this.map.tagFilter;
        },

        escapeXml(s) {
            return String(s).replace(/[<>&"]/g, c => (
                { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]
            ));
        },

        get galaxySvg() {
            const active = this.galaxyActiveTag;
            const interactive = this.galaxyInteractive;
            return this.map.points.map((p) => {
                const cx = this.galaxyX(p.x).toFixed(1);
                const cy = this.galaxyY(p.y).toFixed(1);
                const color = this.tagColor(p.tag);
                const dim = (active != null && p.tag !== active) ? ' data-dim="true"' : '';
                const hit = interactive
                    ? `<circle data-id="${p.id}" cx="${cx}" cy="${cy}" r="12" fill="transparent"></circle>`
                    : '';
                return `<g class="galaxy-pt"${dim}>${hit}`
                    + `<circle class="galaxy-dot" cx="${cx}" cy="${cy}" r="4" fill="${color}"></circle>`
                    + `</g>`;
            }).join('');
        },
```

- [ ] **Step 3: Add the interaction handlers to `analytics.js`**

Add after `galaxySvg`:

```javascript
        onGalaxyHover(event) {
            if (!this.galaxyInteractive) return;
            const el = event.target.closest('[data-id]');
            if (el) this.map.selectedId = Number(el.dataset.id);
        },

        onGalaxyClick(event) {
            if (!this.galaxyInteractive) return;
            const el = event.target.closest('[data-id]');
            const id = el ? Number(el.dataset.id) : null;
            // tap a dot to pin it; tap it again, or tap empty space, to clear
            this.map.selectedId = (id === this.map.selectedId) ? null : id;
        },

        toggleTagFilter(tag) {
            this.map.tagFilter = (this.map.tagFilter === tag) ? null : tag;
            this.map.selectedId = null;
        },
```

- [ ] **Step 4: Add the panel markup to `analytics.html`**

Insert between line 100 (`</div>` closing "Bookmarks over time") and line 102 (`<!-- Top tags + top domains -->`):

```html
            <!-- Collection map: 2D projection of every bookmark embedding -->
            <div class="bg-white rounded-xl border border-slate-200 p-5" x-ref="mapPanel">
                <div class="flex items-baseline justify-between mb-1">
                    <h2 class="text-sm font-semibold text-slate-900">Collection map</h2>
                    <span class="text-xs text-slate-500" x-show="map.loaded && map.points.length > 0"
                        x-text="map.points.length + (map.points.length === 1 ? ' bookmark' : ' bookmarks')"></span>
                </div>
                <p class="text-xs text-slate-500 mb-3">Each dot is a bookmark; dots sit closer when their content is more alike.</p>

                <div x-show="!map.loaded" class="animate-pulse bg-slate-100 rounded-lg" style="height:320px"></div>

                <p x-show="map.loaded && map.points.length === 0"
                    class="text-sm text-slate-500 py-12 text-center">
                    Save a few more bookmarks to see your collection map.</p>

                <div x-show="map.loaded && map.points.length > 0" class="relative"
                    tabindex="-1" @keydown.escape="map.selectedId = null">

                    <div class="flex flex-wrap gap-x-3 gap-y-1 mb-2" x-show="map.clusters.length > 0">
                        <template x-for="c in map.clusters" :key="'lg-' + c.tag">
                            <button type="button" @click="toggleTagFilter(c.tag)"
                                class="inline-flex items-center gap-1.5 text-xs text-slate-600 rounded px-1 -mx-1 hover:bg-slate-50 transition"
                                :class="map.tagFilter === c.tag ? 'ring-1 ring-indigo-300 bg-indigo-50' : ''">
                                <span class="w-2.5 h-2.5 rounded-full shrink-0" :style="'background:' + tagColor(c.tag)"></span>
                                <span x-text="c.tag"></span>
                            </button>
                        </template>
                    </div>

                    <svg viewBox="0 0 460 320" class="galaxy-svg w-full block" style="max-height:320px"
                        role="img"
                        :aria-label="map.points.length + ' bookmarks across ' + map.clusters.length + ' topic clusters'"
                        @mouseover="onGalaxyHover($event)" @click="onGalaxyClick($event)"
                        x-html="galaxySvg"></svg>

                    <p x-show="!galaxyInteractive" class="text-xs text-slate-500 mt-1"
                        x-text="'Showing ' + map.points.length + ' bookmarks — hovering is off at this size; open one from the lists below.'"></p>

                    <template x-if="selectedPoint">
                        <div class="absolute left-2 right-2 bottom-2 sm:left-auto sm:right-2 sm:top-2 sm:bottom-auto sm:w-56
                                    bg-white border border-slate-200 rounded-lg shadow-lg p-3 text-xs">
                            <p class="font-semibold text-slate-900 line-clamp-2" x-text="selectedPoint.title"></p>
                            <p class="text-slate-500 truncate mt-0.5" x-text="selectedPoint.domain"></p>
                            <a :href="selectedPoint.url" target="_blank" rel="noopener"
                                class="inline-flex items-center gap-1 mt-2 font-medium text-indigo-600 hover:text-indigo-500">
                                Open <span aria-hidden="true">↗</span>
                            </a>
                        </div>
                    </template>
                </div>
            </div>

```

- [ ] **Step 5: Add `.galaxy-*` CSS**

Append to `app/static/style.css`:

```css

/* Collection map (analytics): dots injected via x-html like the timeline
   bars, so dim/hover styling is plain CSS. */
.galaxy-svg {
    touch-action: manipulation;
}

.galaxy-pt {
    transition: opacity 0.15s ease;
}

.galaxy-pt[data-dim="true"] {
    opacity: 0.2;
}
```

- [ ] **Step 6: Bump `analytics.js` cache-bust**

In `app/templates/analytics.html:10`, change `analytics.js?v=1.0.1` to `analytics.js?v=1.0.2`.

- [ ] **Step 7: Verify in the browser**

Run: `./venv/bin/python -m uvicorn app.main:app --port 8011` (from `/var/www/bookmark`; stop with Ctrl-C when done).
In a browser at `http://localhost:8011/analytics` with at least 3 bookmarks that have embeddings:
- Panel shows a skeleton, then a scatter after scrolling it into view (Network tab shows `api/analytics/map` fired only once, on approach).
- Hovering a dot pins a callout (title + domain + Open); other-tag dots dim.
- Clicking a legend swatch dims everything except that tag; clicking it again clears.
- `Esc` clears the selection.
- Empty DB (or <3 embeddings): "Save a few more bookmarks…" text, no SVG, no console errors.

Then resize to 375px wide (DevTools device toolbar):
- No horizontal scroll on the page.
- Tapping a dot shows the callout as a **full-width bar at the bottom of the panel**; `Open` works; tapping empty space clears it.

- [ ] **Step 8: Run the Python suite (nothing should have moved)**

Run: `./venv/bin/python -m pytest -q`
Expected: PASS (all)

- [ ] **Step 9: Commit**

```bash
git add app/static/analytics.js app/templates/analytics.html app/static/style.css
git commit -m "feat: collection-map panel on the analytics page

Lazy-loaded SVG scatter of the /api/analytics/map projection: dots colored by
first tag, tap/hover pins a callout, legend swatches filter by tag, callout
becomes a bottom bar below sm. >800 points falls back to a plain scatter.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0173bhWBotGAwX6Scwbtn3Gt"
```

---

## Task 4: Match constellation (search page)

**Files:**
- Modify: `app/static/app.js` — add state + methods to the `bookmarkApp` Alpine component (object literal starts `:2`, state block ends `:23` at `brokenThreshold: 1,`; `matchPercent` is at `:133`; file ends `:374`).
- Modify: `app/templates/index.html` — the shared `bookmark_card()` macro root is `:201`; the *Related by meaning* section is `:322`–`:337`.
- Modify: `app/static/style.css` — append `.star-*` rules.

**Interfaces:**
- Consumes: `this.semanticBookmarks` (getter, `:129` — bookmarks with `match === 'semantic'`, each carrying `id`, `title`, `url`, `score`), `this.searchQuery` (`:7`).
- Produces (used by the template): `hoveredId` state, `constellationSvg` getter, `constellationHover($event)`, `constellationClick($event)`.

- [ ] **Step 1: Add `hoveredId` state to `app.js`**

In the `bookmarkApp` object, add after `brokenThreshold: 1,` (`:23`):

```javascript

        // Search-results constellation: id of the semantic result currently
        // hovered or focused, mirrored between its card and its star.
        hoveredId: null,
```

- [ ] **Step 2: Add the constellation helpers to `app.js`**

Add immediately after `matchPercent(score)` (`:133`–`:135`):

```javascript

        get prefersReducedMotion() {
            return !!(window.matchMedia
                && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        },

        starLabel(text) {
            const s = (text || '').trim();
            return s.length > 15 ? s.slice(0, 14).trimEnd() + '…' : s;
        },

        scrollCardIntoView(id) {
            const el = document.getElementById('bm-' + id);
            if (el) el.scrollIntoView({
                behavior: this.prefersReducedMotion ? 'auto' : 'smooth',
                block: 'center',
            });
        },

        escapeXml(s) {
            return String(s).replace(/[<>&"]/g, c => (
                { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]
            ));
        },

        // Full inner markup for the banner <svg> (viewBox 0 0 640 190).
        // Built as a string because Alpine's <template x-for> cloning breaks
        // inside <svg> — same reason as barsSvg in analytics.js.
        get constellationSvg() {
            const pts = this.semanticBookmarks;
            const n = pts.length;
            if (n === 0) return '';

            const CX = 320, CY = 98;
            const RX_MIN = 46, RX_MAX = 150, RY_MIN = 30, RY_MAX = 70;
            const scores = pts.map(b => b.score || 0);
            const lo = Math.min(...scores), hi = Math.max(...scores);
            const norm = s => (hi - lo < 1e-9) ? 0.55 : (s - lo) / (hi - lo);
            const base = -Math.PI * 0.85;
            const step = (1.55 * Math.PI) / Math.max(n - 1, 1);

            const rings = [
                ['150', '70', '0.5'], ['98', '50', '0.35'], ['46', '30', '0.25'],
            ].map(([rx, ry, op]) =>
                `<ellipse cx="${CX}" cy="${CY}" rx="${rx}" ry="${ry}" fill="none" stroke="#e2e8f0" stroke-opacity="${op}"></ellipse>`
            ).join('');

            const stars = pts.map((b, i) => {
                const t = norm(b.score || 0);
                const jitter = ((((b.id * 2654435761) >>> 0) % 1000) / 1000 - 0.5) * 0.28;
                const ang = base + i * step + jitter;
                const x = +(CX + (RX_MAX - t * (RX_MAX - RX_MIN)) * Math.cos(ang)).toFixed(1);
                const y = +(CY + (RY_MAX - t * (RY_MAX - RY_MIN)) * Math.sin(ang)).toFixed(1);
                const dot = +(2 + t * 2.8).toFixed(1);
                const lineOpacity = +(0.1 + t * 0.32).toFixed(2);
                const labelY = Math.sin(ang) >= -0.2
                    ? +(y + dot + 11).toFixed(1)
                    : +(y - dot - 6).toFixed(1);
                const hot = (b.id === this.hoveredId) ? ' is-hot' : '';
                return `<g class="star-g${hot}" data-id="${b.id}">`
                    + `<line class="star-line" x1="${CX}" y1="${CY}" x2="${x}" y2="${y}" stroke="#6366f1" stroke-opacity="${lineOpacity}" stroke-width="1"></line>`
                    + `<circle class="star-dot" cx="${x}" cy="${y}" r="${dot}" fill="#6366f1" style="animation-delay:-${(b.id % 7) * 0.5}s"></circle>`
                    + `<text class="star-label" x="${x}" y="${labelY}" text-anchor="middle" fill="#4f46e5" style="font-size:9px;font-weight:600">${this.escapeXml(this.starLabel(b.title || b.url))}</text>`
                    + `</g>`;
            }).join('');

            const q = this.searchQuery.trim();
            const caption = q.length > 40 ? q.slice(0, 39).trimEnd() + '…' : q;
            const center = `<circle cx="${CX}" cy="${CY}" r="5.5" fill="#4f46e5"></circle>`
                + `<circle cx="${CX}" cy="${CY}" r="10" fill="none" stroke="#4f46e5" stroke-opacity="0.3" stroke-width="1.5"></circle>`
                + `<text x="${CX}" y="78" text-anchor="middle" fill="#64748b" style="font-size:10px;font-weight:600">“${this.escapeXml(caption)}”</text>`;

            return rings + stars + center;
        },

        constellationHover(event) {
            const g = event.target.closest('[data-id]');
            if (g) this.hoveredId = Number(g.dataset.id);
        },

        constellationClick(event) {
            const g = event.target.closest('[data-id]');
            if (g) this.scrollCardIntoView(Number(g.dataset.id));
        },
```

- [ ] **Step 3: Add the card `:id`, ring, and hover/focus handlers in `index.html`**

Replace the macro root `<div>` (`:201`):

```html
            <div class="bg-white rounded-xl border border-slate-200 p-4 hover:border-slate-300 hover:shadow-md transition duration-200 flex flex-col">
```

with:

```html
            <div :id="'bm-' + bm.id"
                class="bg-white rounded-xl border border-slate-200 p-4 hover:border-slate-300 hover:shadow-md transition duration-200 flex flex-col"
                :class="hoveredId === bm.id && bm.match === 'semantic' ? 'ring-2 ring-indigo-400' : ''"
                @mouseenter="if (bm.match === 'semantic') hoveredId = bm.id"
                @mouseleave="if (bm.match === 'semantic') hoveredId = null"
                @focusin="if (bm.match === 'semantic') hoveredId = bm.id"
                @focusout="if (bm.match === 'semantic') hoveredId = null">
```

- [ ] **Step 4: Add the banner SVG in `index.html`**

Between the section header `</div>` (`:330`) and the results grid `<div class="grid ...">` (`:331`), insert:

```html
                    <!-- Decorative: how close each result sits to the search, by meaning -->
                    <div class="mb-5 rounded-xl border border-slate-200 bg-gradient-to-b from-white to-slate-50/70 overflow-hidden">
                        <svg viewBox="0 0 640 190" class="w-full block" style="max-height:190px" aria-hidden="true"
                            @mouseover="constellationHover($event)" @mouseleave="hoveredId = null"
                            @click="constellationClick($event)"
                            x-html="constellationSvg"></svg>
                    </div>
```

- [ ] **Step 5: Add the `.star-*` CSS**

Append to `app/static/style.css`:

```css

/* Search-results constellation: stars injected via x-html (see app.js
   constellationSvg); hover state is plain CSS keyed off .is-hot. The global
   prefers-reduced-motion rule above already neutralizes the animation. */
@keyframes twinkle {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 1; }
}

.star-dot {
    animation: twinkle 3.4s ease-in-out infinite;
    transform-box: fill-box;
    transform-origin: center;
    transition: transform 0.18s ease, filter 0.18s ease;
}

.star-label {
    opacity: 0;
    transition: opacity 0.18s ease;
}

.star-line {
    transition: stroke-opacity 0.18s ease;
}

.star-g.is-hot .star-dot {
    transform: scale(1.7);
    filter: drop-shadow(0 0 5px rgba(99, 102, 241, 0.85));
}

.star-g.is-hot .star-label {
    opacity: 1;
}

.star-g.is-hot .star-line {
    stroke-opacity: 0.8;
}
```

- [ ] **Step 6: Bump cache-bust strings in `index.html`**

- `:10` — `style.css?v=1.0.3` → `style.css?v=1.0.4`
- `:11` — `app.js?v=1.0.9` → `app.js?v=1.0.10`

- [ ] **Step 7: Verify in the browser**

Run: `./venv/bin/python -m uvicorn app.main:app --port 8011` (from `/var/www/bookmark`).
At `http://localhost:8011/` with a search that returns semantic results (needs bookmarks with embeddings; the real fastembed model loads on first use — allow a few seconds, or seed embeddings directly):
- Banner shows the query at center, one twinkling star per related result, closer stars for higher `% match`.
- Hovering a result card → its star enlarges, glows, shows its label, brightens its line; the card gets an indigo ring.
- Hovering a star → the matching card gets the ring; clicking the star scrolls that card to center.
- Tab key through the result cards → the focused card's star lights (focus path).
- One semantic result → single star mid-band, no error. Zero → section (and banner) absent.
- No horizontal scroll at 375px; banner ≈100px tall there.
- OS "reduce motion" on → no twinkle, no scale transition, `scrollIntoView` jumps instead of animating.

- [ ] **Step 8: Run the Python suite**

Run: `./venv/bin/python -m pytest -q`
Expected: PASS (all)

- [ ] **Step 9: Commit**

```bash
git add app/static/app.js app/templates/index.html app/static/style.css
git commit -m "feat: match constellation above the Related by meaning results

Decorative SVG banner: the search at center, one star per semantic result
placed closer for a stronger embedding match. Hover/focus a card to light its
star; hover a star to ring + scroll its card. Motion is transform/opacity only
and off under prefers-reduced-motion.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0173bhWBotGAwX6Scwbtn3Gt"
```

---

## Task 5: Template-markup regression tests + final verification

**Files:**
- Test: `tests/test_api.py` — two assertions that the new panels render.

**Interfaces:**
- Consumes: the `/` and `/analytics` HTML routes (`app/main.py:120`, and the index route) — templates are served raw (Alpine runs client-side), so literal attribute strings appear in `resp.text`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api.py` after `test_analytics_page` (`:136`):

```python
async def test_analytics_page_has_collection_map_panel(client):
    resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "Collection map" in resp.text
    assert 'x-html="galaxySvg"' in resp.text


async def test_index_page_has_constellation_banner(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'x-html="constellationSvg"' in resp.text
```

- [ ] **Step 2: Run them**

Run: `./venv/bin/python -m pytest tests/test_api.py -k "collection_map_panel or constellation_banner" -v`
Expected: PASS (Tasks 3 and 4 already added the markup). If either FAILS, the corresponding template edit is missing — fix the template, not the test.

- [ ] **Step 3: Full suite**

Run: `./venv/bin/python -m pytest -q`
Expected: PASS (all)

- [ ] **Step 4: Manual cross-check at two widths**

Run the app (`./venv/bin/python -m uvicorn app.main:app --port 8011`) and, with a seeded collection, walk the spec's build-order step 4 checklist:
- `/` at desktop + 375px: many / one / zero semantic results; card↔star highlight both directions; keyboard focus lights the star; reduced-motion; no horizontal scroll.
- `/analytics` at desktop + 375px: lazy-load fires on scroll; tap a dot → callout (bottom bar on mobile); `Open ↗` works; tap-away and `Esc` clear; legend filter dims; empty-collection copy.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api.py
git commit -m "test: assert the constellation banner and collection-map panel render

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0173bhWBotGAwX6Scwbtn3Gt"
```

- [ ] **Step 6: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to decide how to integrate `semantic-visuals` (PR vs. merge).

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| A — placement / banner in *Related by meaning* | 4 (Step 4) |
| A — `constellation()` layout math (norm, elliptical radius, jitter, dead sector, labelBelow) | 4 (Step 2, `constellationSvg`) |
| A — `hoveredId`, card `@mouseenter/@focusin`, ring, `:id`, star hover→ring→scroll | 4 (Steps 1, 3, 4) |
| A — `starLabel` truncation; caption 40-char cap; curly quotes | 4 (Step 2) |
| A — CSS: twinkle, `.is-hot`, transform/opacity only, rely on global reduced-motion | 4 (Step 5) |
| A — edge cases: 0 / 1 result; long caption; ≤12 stars | 4 (Step 2 `norm` guard + Step 7 checks) |
| A — mobile: self-scaling banner, ambient-only, focus still fires | 4 (Steps 4, 7) |
| B — `project_2d()`: `<3` guard, center, SVD, `u[:, :2]*s[:2]`, per-axis min-max, degenerate→0.5, round 4dp, id order | 1 |
| B — `/api/analytics/map`: reuse index, `is_stale`/`refresh`, empty→`{points:[],clusters:[]}`, domain rule, first-tag, top-8 non-null clusters, `url` in payload | 2 |
| B — frontend: `map` state, IntersectionObserver lazy-load, palette + `tagColor`, viewBox 460×320 + flip-y, `x-html` string build, `>800` fallback | 3 (Steps 1, 2) |
| B — interaction: one `selectedId` for hover+tap, `@keydown.escape`, dim by tag, legend filter buttons | 3 (Steps 2, 3, 4) |
| B — callout replaces floating tooltip; bottom bar `< sm`; `Open ↗` real `<a>` | 3 (Step 4) |
| B — `role="img"` + `:aria-label`; skeleton + empty states | 3 (Step 4) |
| B — mobile: `touch-action`, transparent `r=12` hit target, no `<a>` dots | 3 (Steps 2, 5) + Global Constraints |
| B — tests: `project_2d` shape/determinism/degenerate; endpoint contract + empty guard | 1 (Step 1), 2 (Step 1) |
| Cache-bust `?v=` bumps | 3 (Step 6), 4 (Step 6) |
| Build order (backend → map panel → constellation → verify) | Task order 1→2→3→4→5 |

No gaps.

**2. Placeholder scan** — no "TBD/TODO/handle edge cases/similar to Task N". Every code step has literal code; every test step has literal assertions; every run step has an exact command + expected result.

**3. Type consistency**
- `project_2d` returns `list[tuple[int, float, float]]` in Task 1; Task 2 consumes it as `for bid, px, py in coords` and builds `position = {bid: (px, py)}`. ✓
- Task 2 response keys `id,x,y,title,domain,url,tag` + `clusters:[{tag,count}]`; Task 2 test asserts exactly `{"id","x","y","title","domain","url","tag"}`; Task 3 `galaxySvg`/`selectedPoint`/callout read `p.x,p.y,p.id,p.tag,p.title,p.domain,p.url` and `c.tag`. ✓
- `hoveredId` (Task 4) set by card handlers and `constellationHover`, read by `constellationSvg` and the card `:class`. ✓
- `map.selectedId` / `map.tagFilter` (Task 3) — set in `onGalaxyHover`/`onGalaxyClick`/`toggleTagFilter`/`@keydown.escape`, read in `galaxyActiveTag`/`selectedPoint`/`galaxySvg`/legend `:class`. ✓
- `escapeXml` defined in both components (Task 3 Step 2, Task 4 Step 2) — intentional, each Alpine component is a separate object.
- `galaxyX/galaxyY` use viewBox `460×320`; the template `<svg viewBox="0 0 460 320">` matches. ✓
- Constellation viewBox `640×190`, `constellationSvg` uses `CX=320, CY=98` and max ry 70 → y ∈ [28,168] within 190. ✓
