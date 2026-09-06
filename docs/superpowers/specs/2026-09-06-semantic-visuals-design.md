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
  `jitter(id) = ((Math.imul(id, 2654435761) >>> 0) % 1000) / 1000 - 0.5`
  (deterministic, stable between renders; `Math.imul` keeps the hash exact for
  ids past 2^24). The `1.55*PI` sweep (not full `2*PI`) spreads the stars over
  an open arc rather than a closed ring. The query caption cannot collide with
  them because it sits above the star band entirely (`y = 18`, band starts at
  `CY - RY_MAX = 28`), not because of the sweep.
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
```

`style.css` already carries a **global** `@media (prefers-reduced-motion:
reduce)` rule that forces `animation-duration`/`transition-duration` to
`0.01ms` on `*` — so the twinkle and every hover transition here are already
neutralized on that setting. No per-feature media query needed; do **not**
add a second one.

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

### Mobile / touch (A)

- The banner `<svg>` is `w-full` with a fixed `0 0 640 190` viewBox, so at a
  ~343px content width it renders ~102px tall with no horizontal scroll — it
  self-scales, no breakpoint needed. Result cards are already single-column
  (`grid-cols-1`) below it.
- There is no hover on touch, and the card↔star highlight is a **desktop
  enhancement only**. On touch the constellation is purely ambient — it still
  conveys relative closeness by distance/size, which is the point. The `%
  match` bar on each card carries the exact number. No tap handler on stars
  (a ~2–5px target scaled down on mobile isn't a reliable tap target and the
  value doesn't justify adding oversized hit circles here).
- `@focusin`/`@focusout` on the card still fire on mobile when a control
  inside the card (Open / Edit) is tapped — harmless, briefly lights the star.
- Star labels are hover-only, so their small rendered size on mobile is moot.

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
  `{"points": [{"id","x","y","title","domain","url","tag"}], "clusters": [...]}`
  (`url` is needed by the callout's "Open" link; `domain` is kept
  pre-derived so the frontend needn't parse it.)
- Cost note: SVD on `(n, 384)` for `n` in the hundreds is a few ms; still,
  the frontend lazy-loads this (below) so it never blocks first paint.

### Frontend (`app/static/analytics.js`, `app/templates/analytics.html`)

- New Alpine state:
  `map: { points: [], clusters: [], loaded: false, selectedId: null }`.
  One `selectedId` drives both mouse hover and touch tap — there is no
  separate hover state (see "Interaction model" below).
- **Lazy load:** an `x-intersect` (Alpine plugin not present) — instead use a
  plain `IntersectionObserver` created in `init()` watching the panel's
  container `$refs.mapPanel`; on first intersect, `fetch('api/analytics/map')`,
  set `map.points/clusters`, `map.loaded = true`, disconnect.
- **Palette:** fixed 8-color array (indigo-500, teal-500, amber-500,
  rose-500, sky-500, violet-500, emerald-500, orange-500 hexes) keyed by the
  `clusters` order; `tagColor(tag)` returns the palette color or
  `#94a3b8` (slate-400, "other").
- **SVG:** `viewBox="0 0 460 320"`, inner padding 16px; map point `x,y` in
  `[0,1]` to `[pad, 460-pad] × [304-pad, pad]` (flip y). `w-full`, so it
  self-scales — at ~343px content width it renders ~239px tall, no horizontal
  scroll. `touch-action: manipulation` on the `<svg>`.
- **Rendering:** same `x-html` string-building approach the file already uses
  for `barsSvg` (Alpine's `<template>` cloning breaks inside `<svg>` — see the
  existing comment at `analytics.js:56`). Per point, a `<g class="galaxy-pt"
  data-id data-tag>` containing:
  - a transparent hit target `<circle r="12" fill="transparent">` (so the tap
    target is ~24px on mobile even though the visible dot is small),
  - the visible `<circle class="galaxy-dot" r="4" :fill="tagColor(tag)">`.
  The `<g>` is **not** wrapped in `<a>` — navigation happens from the callout
  (below), which keeps a single code path for mouse and touch and avoids
  accidental navigation on a mistap. Middle-click/⌘-click is a desktop-only
  loss we accept; the callout's Open link is a real `<a>` and covers
  keyboard.
  - `>800` points: skip the per-point hit circles (render bare
    `<circle class="galaxy-dot">` only) and show under the panel: "Showing
    N bookmarks — hovering is disabled at this size; open one from the lists
    below."
- **Interaction model (one path for hover + tap):**
  - Desktop: event-delegated `@mouseover`/`@mouseleave` on the `<svg>` sets /
    clears `map.selectedId` from the nearest `[data-id]`.
  - Touch / click: event-delegated `@click` on the `<svg>` sets
    `map.selectedId` to the tapped dot; a tap with no dot under it (or a tap
    on the already-selected dot) clears it. `@click` also covers the
    "no hover" case on hybrid devices.
  - `@keydown.escape` on the panel clears `map.selectedId`.
  - While `selectedId` is set, dots whose `data-tag` differs from the
    selected dot's tag get `opacity:.2` (CSS rule keyed off a class +
    `data-tag` attr on the `<svg>`; no markup rebuild).
- **Callout (replaces the floating tooltip):** when `map.selectedId` is set,
  show a callout with the point's `title`, `domain`, and an
  `<a href target="_blank" rel="noopener">Open ↗</a>`.
  - `sm+`: positioned near the dot (clamped to stay inside the panel).
  - `< sm`: a full-width bar pinned to the bottom of the panel, so it never
    overflows a narrow screen or sits under the finger.
  - The Open link is the only navigation affordance and is keyboard-focusable.
- **Legend:** row of swatches from `map.clusters` + an "other" swatch, each a
  `<button type="button">` (already gets `touch-action: manipulation` from the
  global rule) that sets a `map.tagFilter`; when set, non-matching dots dim
  the same way. Tapping the active swatch again clears it. Nice to have — can
  ship without if step 2 runs long.
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
  `galaxySvg` getter, `@mouseover`/`@click`/`@keydown.escape` handlers,
  callout positioning.
- `app/templates/analytics.html` — panel markup (SVG + callout, `sm`
  breakpoint on callout position); bump `?v=` for `analytics.js`.
- `app/static/style.css` — `.galaxy-dot` opacity transition + the
  selected/filter dim rule; `touch-action: manipulation` on `.galaxy-svg`.

### Mobile / touch (B)

- SVG `w-full` + fixed viewBox → self-scales, ~239px tall at 343px width, no
  horizontal scroll. Panel sits in the normal single-column analytics flow.
- Every dot has a transparent `r=12` hit circle → ~24px tap target regardless
  of the small visible radius.
- No `<a>`-wrapped dots → a mistap never navigates. Selection (tap) shows the
  callout; the callout's `Open ↗` link is the single deliberate navigation.
- `< sm`: callout is a full-width bottom bar inside the panel — never
  overflows the viewport, never sits under the finger.
- `touch-action: manipulation` on the SVG kills the 300ms double-tap-zoom
  delay; page zoom itself stays enabled (no `user-scalable=no` anywhere).
- Legend swatches are `<button>`s — full tap targets, wrap freely.
- Both templates already ship `<meta name="viewport"
  content="width=device-width, initial-scale=1.0">` and no zoom-blocking.

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
  each point has the seven keys (`id,x,y,title,domain,url,tag`), `x`/`y` are
  floats in `[0, 1]`, `clusters` is a
  list of `{tag, count}`. (Follow existing embedding-seeding helpers in the
  test file / `conftest.py`.)

## Build order

1. `project_2d()` + `/api/analytics/map` + their tests (TDD).
2. Collection-map panel wired to the endpoint (lazy load, palette,
   selection + callout, dim-by-tag, states).
3. Constellation: `constellation()` getter + banner SVG + card interaction.
4. Shared `style.css` additions; `?v=` bumps; manual pass in the running app
   at **both a desktop width and a 375px mobile viewport**:
   - search: many / one / zero semantic results; reduced-motion on; keyboard
     tab through result cards lights the right star; no horizontal scroll on
     the banner at 375px.
   - analytics: seeded collection; lazy-load fires on scroll; tap a dot on a
     touch emulator → callout appears as a bottom bar, `Open ↗` works, tap
     elsewhere dismisses; legend filter dims correctly; `>800`-point fallback
     copy shows; empty-collection copy shows.

## Risks / open questions

- `np.linalg.svd` on a wide matrix (`n < 384`) via `full_matrices=False` is
  fine and fast; if a collection ever exceeds a few thousand bookmarks the
  endpoint is still sub-100ms and SVG dot count is the real limit — the >800
  fallback covers rendering.
- The legend-as-filter interaction is marked nice-to-have; drop it if step 2
  runs long.
- Palette collision with existing teal domain bars is intentional (shared
  system), not a conflict.
- Mobile: both features degrade to non-interactive ambient visuals only where
  hover was the affordance (constellation entirely; galaxy keeps tap). This is
  a deliberate call, not a gap — the exact numbers live in the cards / tag
  lists, which are the accessible + small-screen path. No dedicated mobile
  layout, no separate breakpoint work beyond the callout position swap.
