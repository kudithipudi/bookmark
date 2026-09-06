# Semantic Visuals — Design

Date: 2026-09-06
Status: approved for planning

## Summary

Two additions that make the app's embedding features *visible*, sharing one
visual language (indigo starfield on a light card, inline SVG, no chart
library, `prefers-reduced-motion` aware):

- **A — Match constellation:** a decorative star map above the search page's
  "Related by meaning" section showing how close each semantic result sits to
  the query.
- **B — Collection map (semantic galaxy):** an analytics panel that projects
  every bookmark embedding to 2D so topic clusters are visible at a glance.

Neither feature changes existing behavior; both are additive panels.

## Non-goals

- No new Python dependency. Projection uses `numpy` (already in the venv via
  `semantic_index.py`).
- No vector database, no UMAP/t-SNE. PCA (via SVD) only.
- Constellation is not an accessible data view — the existing per-card
  `% match` bar and the analytics tag panels remain the textual equivalent.
- No pan/zoom, no animation beyond a subtle twinkle and hover transitions.
- No backend change for feature A (`score` is already serialized per
  semantic bookmark in `list_bookmarks`, `app/main.py`).

## Feature A — Match constellation

### Placement

Inside the existing block in `app/templates/index.html`:

```
<template x-if="!loading && semanticBookmarks.length > 0">
  <section ...>
    <div> ... "Related by meaning" heading ... </div>
    <!-- NEW: constellation banner here -->
    <div class="grid ...">  <!-- existing results grid --> </div>
  </section>
</template>
```

The banner is a bordered, rounded container (matching the card styling
already in the file) holding one full-width `<svg>`, `aria-hidden="true"`.

### Layout math (in `app/static/app.js`)

New Alpine state: `hoveredId: null`.

New getter `constellation()` returning an array of
`{ id, x, y, dot, lineOpacity, labelBelow }`, computed from
`this.semanticBookmarks` and `this.searchQuery`:

- Fixed `viewBox` `0 0 640 190`; center `(320, 98)`.
- `norm(score)`: linear map of the visible set's `[min..max]` similarity onto
  `[0, 1]`. If `min === max` (one result, or all identical), `norm → 0.55`.
- Radius: elliptical. `rx = RX_MAX - norm * (RX_MAX - RX_MIN)`,
  `ry = RY_MAX - norm * (RY_MAX - RY_MIN)` with
  `RX_MIN≈46, RX_MAX≈150, RY_MIN≈30, RY_MAX≈70` (wider than tall to use the
  banner width). Nearest match → smallest radius.
- Angle: `base = -PI*0.85`; `step = 1.55*PI / max(n-1, 1)`;
  `angle = base + i*step + jitter(id)*0.28` where
  `jitter(id) = (((id * 2654435761) >>> 0) % 1000) / 1000 - 0.5` (deterministic,
  stable between renders). The `1.55*PI` sweep (not full `2*PI`) keeps a dead
  sector at the bottom so stars never collide with the query caption.
- `dot = 2 + norm * 2.8`; `lineOpacity = 0.1 + norm * 0.32`.
- `labelBelow = sin(angle) >= -0.2` (place the label under the dot unless the
  dot is in the upper arc near the caption).

Helper `starLabel(title)`: truncate to 15 chars + `…`.

The SVG renders, in order: 3 faint concentric guide ellipses, a soft radial
halo, one `<g class="star-g" :data-id>` per point (connector `<line>`, `<circle
class="star-dot">`, hover-only `<text class="star-label">`), then the center
node (filled dot + ring) and the caption `<text>` showing
`"<searchQuery>"` in curly quotes, positioned *above* the center node.

### Interaction

- Each semantic result card (the `bookmark_card()` macro is shared; gate the
  new handlers on `bm.match === 'semantic'`) gets
  `@mouseenter="hoveredId = bm.id"`, `@mouseleave="hoveredId = null"`,
  `@focusin="hoveredId = bm.id"`, `@focusout="hoveredId = null"`.
- The card root also gets `:class="hoveredId === bm.id && bm.match === 'semantic' ? 'ring-2 ring-indigo-400' : ''"`.
- In the SVG, `<g class="star-g" :class="hoveredId === p.id ? 'is-hot' : ''">`.
- Hovering a star sets `hoveredId = p.id` and, on click, calls
  `scrollCardIntoView(p.id)` — `document.getElementById('bm-' + id)?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' })`.
  (Add `:id="'bm-' + bm.id"` to the card root.)
- `star-g` has `tabindex="0"` and `role="button"` **only when** pointer hover
  is not the sole affordance — decision: keep stars pointer-only, the cards are
  the keyboard path. Rationale: duplicating 12 tab stops for a decorative
  mirror of the cards adds noise; card `@focusin` already lights the star.

### CSS (`app/static/style.css`)

```css
@keyframes twinkle { 0%,100% { opacity:.5 } 50% { opacity:1 } }
.star-dot {
  animation: twinkle 3.4s ease-in-out infinite;
  transform-box: fill-box; transform-origin: center;
  transition: transform .18s ease, filter .18s ease;
}
.star-label { transition: opacity .18s ease; opacity: 0; }
.star-line  { transition: stroke-opacity .18s ease; }
.star-g.is-hot .star-dot  { transform: scale(1.7); filter: drop-shadow(0 0 5px rgba(99,102,241,.85)); }
.star-g.is-hot .star-label { opacity: 1; }
.star-g.is-hot .star-line  { stroke-opacity: .8; }
@media (prefers-reduced-motion: reduce) {
  .star-dot, .star-label, .star-line { animation: none; transition: none; }
}
```

Per-dot `animation-delay: -<n>s` (inline, derived from `id % 7`) so stars
don't twinkle in unison.

### Files touched (A)

- `app/static/app.js` — `hoveredId`, `constellation()`, `starLabel()`,
  `scrollCardIntoView()`, `reducedMotion` helper.
- `app/templates/index.html` — banner SVG; card handlers + `:id` + ring class.
- `app/static/style.css` — block above. Bump `?v=` query strings in
  `index.html` for `app.js` / `style.css`.

### Edge cases (A)

- 0 semantic results: whole section already hidden — nothing renders.
- 1 result: `norm → 0.55`, single star mid-band, no divide-by-zero.
- Very long query caption: `<text>` is not wrapped; cap display to ~40 chars
  + `…` in `constellation()` output (`captionText`).
- Many results (limit is 12, `semantic_search_limit`): 12 stars fit the sweep.

## Feature B — Collection map (semantic galaxy)

### Backend

New helper on `SemanticIndex` (`app/services/semantic_index.py`):

```python
def project_2d(self) -> list[tuple[int, float, float]]:
    """(id, x, y) for every indexed embedding, PCA to 2D, each axis
    min-max scaled to [0, 1]. Empty list if fewer than 3 rows."""
```

- Uses `self._ids` / `self._matrix` (already L2-normalized rows). Caller is
  responsible for `refresh()` (same contract as `search`).
- `if self._matrix is None or self._matrix.shape[0] < 3: return []`
- Center: `X = self._matrix - self._matrix.mean(axis=0, keepdims=True)`
- `U, S, _ = np.linalg.svd(X, full_matrices=False)`
- `coords = U[:, :2] * S[:2]`  (shape `(n, 2)`; if only 1 component is
  non-degenerate, second column is ~0 → scales to 0.5 for all, acceptable)
- Per axis: `(c - c.min()) / (c.max() - c.min())` guarding `max == min → 0.5`.
- Round to 4 decimals; return `list(zip(ids, xs, ys))`.

New route in `app/main.py`:

```python
@app.get("/api/analytics/map")
async def get_analytics_map(request: Request):
```

- `db = request.app.state.db`; `index = await get_semantic_index(request.app.state)`
- `await index.refresh(db)` if stale (mirror `search`), then `coords = index.project_2d()`
- If `coords == []`: return `{"points": [], "clusters": []}`.
- Fetch `id, title, url, tags` for the projected ids; build:
  - `domain`: `urlparse(url).hostname` minus `www.` (same rule as
    `get_analytics`).
  - `tag`: first non-empty comma-split tag, else `None`.
- Cluster legend: `Counter` of the per-point `tag`; the top 8 tags become the
  colored set, everything else (and `None`) renders as "other" grey. Return
  `clusters: [{"tag": t, "count": n}]` for those top 8.
- Response:
  `{"points": [{"id","x","y","title","domain","tag"}], "clusters": [...]}`
- Cost note: SVD on `(n, 384)` for `n` in the hundreds is a few ms; still,
  the frontend lazy-loads this (below) so it never blocks first paint.

### Frontend (`app/static/analytics.js`, `app/templates/analytics.html`)

- New Alpine state: `map: { points: [], clusters: [], loaded: false, hoverId: null }`.
- **Lazy load:** an `x-intersect` (Alpine plugin not present) — instead use a
  plain `IntersectionObserver` created in `init()` watching the panel's
  container `$refs.mapPanel`; on first intersect, `fetch('api/analytics/map')`,
  set `map.points/clusters`, `map.loaded = true`, disconnect.
- **Palette:** fixed 8-color array (indigo-500, teal-500, amber-500,
  rose-500, sky-500, violet-500, emerald-500, orange-500 hexes) keyed by the
  `clusters` order; `tagColor(tag)` returns the palette color or
  `#94a3b8` (slate-400, "other").
- **SVG:** `viewBox="0 0 460 300"`, inner padding 16px; map point `x,y` in
  `[0,1]` to `[pad, 460-pad] × [300-pad, pad]` (flip y).
- **Rendering:** same `x-html` string-building approach the file already uses
  for `barsSvg` (Alpine's `<template>` cloning breaks inside `<svg>` — see the
  existing comment at `analytics.js:56`). Build `<a>` elements wrapping each
  `<circle>`:
  `<a href="<url>" target="_blank" rel="noopener"><circle data-id cx cy r=4 fill=<color> /></a>`.
  - `>800` points: drop the `<a>` wrappers, render bare `<circle>`s, and show a
    line under the panel: "Showing 900 bookmarks — open one from the list
    below." (list = existing top-domains etc.)
- **Hover:** event-delegated `@mouseover`/`@mouseleave` on the `<svg>` (mirror
  `onBarHover`): set `map.hoverId`; a CSS rule dims non-matching-tag dots
  (`.galaxy-dot { transition: opacity .15s } svg[data-dim] .galaxy-dot:not([data-tag="<t>"]) { opacity:.2 }`)
  — simplest: toggle a class on the `<svg>` and set a CSS custom prop for the
  active tag, or just set `opacity` per-dot in a recomputed `x-html`. Decision:
  recompute is simplest and n is small; on hover rebuild the markup string with
  the dimming applied.
- **Tooltip:** a positioned `<div>` (not SVG `<title>`, which is slow to show)
  showing `point.title` + `point.domain`, following the hovered dot; hidden
  when `hoverId === null`.
- **Legend:** row of swatches from `map.clusters` + an "other" swatch, each a
  `<button>` that sets `map.hoverId`-equivalent tag filter on click (nice to
  have; can ship without).
- **`role="img"`** on the `<svg>` with
  `:aria-label="map.points.length + ' bookmarks across ' + map.clusters.length + ' topic clusters'"`.
- **States:** `map.loaded && map.points.length === 0` →
  "Save a few more bookmarks to see your collection map." `!map.loaded` →
  the existing pulse skeleton pattern, height ~320px.

### Placement (B)

`analytics.html`, new `<div class="bg-white rounded-xl border ...">` panel
inserted between "Bookmarks over time" (ends ~L100) and the "Top tags + top
domains" grid (~L103). Heading: "Collection map", sub: "Each dot is a
bookmark; nearby dots are about similar things."

### Files touched (B)

- `app/services/semantic_index.py` — `project_2d()`.
- `app/main.py` — `/api/analytics/map` route.
- `app/static/analytics.js` — `map` state, IntersectionObserver, `tagColor()`,
  `galaxySvg` getter, hover handlers, tooltip position.
- `app/templates/analytics.html` — panel markup; bump `?v=` for `analytics.js`.
- `app/static/style.css` — `.galaxy-dot` transition + dim rule.

### Tests (B)

`tests/test_semantic.py`:
- `project_2d` returns `[]` for 0/1/2 rows.
- For ≥3 distinct rows: length == n, every coord in `[0, 1]`, ids preserved
  in order.
- Determinism: two calls on the same matrix give identical output.
- Degenerate: 3 identical rows → coords all `0.5` (no NaN).

`tests/test_api.py`:
- `GET /api/analytics/map` with an empty DB → `200`,
  `{"points": [], "clusters": []}`.
- With ≥3 seeded bookmarks that have embeddings → `points` length matches,
  each point has the six keys, `x`/`y` are floats in `[0, 1]`, `clusters` is a
  list of `{tag, count}`. (Follow existing embedding-seeding helpers in the
  test file / `conftest.py`.)

## Build order

1. `project_2d()` + `/api/analytics/map` + their tests (TDD).
2. Collection-map panel wired to the endpoint (lazy load, palette, hover,
   tooltip, states).
3. Constellation: `constellation()` getter + banner SVG + card interaction.
4. Shared `style.css` additions; `?v=` bumps; manual pass in the running app —
   many / one / zero semantic results, reduced-motion on, keyboard tab through
   result cards, analytics panel with a seeded collection.

## Risks / open questions

- `np.linalg.svd` on a wide matrix (`n < 384`) via `full_matrices=False` is
  fine and fast; if a collection ever exceeds a few thousand bookmarks the
  endpoint is still sub-100ms and SVG dot count is the real limit — the >800
  fallback covers rendering.
- The legend-as-filter interaction is marked nice-to-have; drop it if step 2
  runs long.
- Palette collision with existing teal domain bars is intentional (shared
  system), not a conflict.
