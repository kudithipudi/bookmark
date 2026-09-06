document.addEventListener('alpine:init', () => {
    Alpine.data('analyticsApp', () => ({
        loading: true,
        totals: { total_bookmarks: 0, total_tags: 0, total_domains: 0, added_this_month: 0 },
        timeline: [],
        topTags: [],
        topDomains: [],
        hoverIndex: null,

        // Collection map (semantic galaxy): lazily fetched when the panel
        // scrolls near the viewport. `selectedId` drives both mouse-hover
        // and touch-tap — there is no separate hover state.
        map: {
            points: [], clusters: [],
            loaded: false, error: false,
            selectedId: null, tagFilter: null,
        },

        async init() {
            try {
                const resp = await fetch('api/analytics');
                const data = await resp.json();
                this.totals = {
                    total_bookmarks: data.total_bookmarks || 0,
                    total_tags: data.total_tags || 0,
                    total_domains: data.total_domains || 0,
                    added_this_month: data.added_this_month || 0,
                };
                this.timeline = (data.timeline || []).map((pt, i, arr) => ({
                    ...pt,
                    // Month alone reads fine mid-year; call out the year at
                    // January and at the first/last point so it's never ambiguous.
                    shortLabel: pt.label.startsWith('Jan') || i === 0 || i === arr.length - 1
                        ? pt.label
                        : pt.label.split(' ')[0],
                }));
                this.topTags = data.top_tags || [];
                this.topDomains = data.top_domains || [];
            } catch (e) {}
            this.loading = false;
            this.$nextTick(() => this.observeMap());
        },

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
                if (!resp.ok) throw new Error(resp.status);
                const data = await resp.json();
                this.map.points = data.points || [];
                this.map.clusters = data.clusters || [];
            } catch (e) {
                this.map.error = true;
            }
            this.map.loaded = true;
        },

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

        escapeAttr(s) {
            return String(s).replace(/[<>&"]/g, c => (
                { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]
            ));
        },

        // Deliberately does NOT read selectedId / tagFilter: x-html rebuilds
        // the whole subtree whenever this getter's dependencies change, and
        // re-parsing ~1300 nodes on every pointer move both stutters and
        // defeats the .galaxy-pt opacity transition. Dimming is applied to
        // the rendered nodes by applyGalaxyDim() instead.
        get galaxySvg() {
            const interactive = this.galaxyInteractive;
            return this.map.points.map((p) => {
                const cx = this.galaxyX(p.x).toFixed(1);
                const cy = this.galaxyY(p.y).toFixed(1);
                const color = this.tagColor(p.tag);
                // data-id lives on the <g> so a pointer event on either child
                // (enlarged hit circle or the small visible dot) resolves via
                // closest('[data-id]'). Only advertised when interactive.
                const id = interactive ? ` data-id="${p.id}"` : '';
                // data-tag is what applyGalaxyDim() compares against; tags are
                // user text, so it has to be attribute-escaped.
                const tag = ` data-tag="${this.escapeAttr(p.tag ?? '')}"`;
                const hit = interactive
                    ? `<circle cx="${cx}" cy="${cy}" r="12" fill="transparent"></circle>`
                    : '';
                return `<g class="galaxy-pt"${id}${tag}>${hit}`
                    + `<circle class="galaxy-dot" cx="${cx}" cy="${cy}" r="4" fill="${color}"></circle>`
                    + `</g>`;
            }).join('');
        },

        // Toggle the data-dim attribute on the already-rendered dots. Driven
        // by x-effect on the map <svg>, so hover/filter changes tween instead
        // of re-parsing the scatter.
        applyGalaxyDim() {
            const svg = this.$refs.galaxySvg;
            if (!svg) return;
            // Touch the point list so this re-runs after x-html repaints too
            // (x-html is bound first; fresh nodes are undimmed either way).
            void this.map.points.length;
            const active = this.galaxyActiveTag;
            svg.querySelectorAll('.galaxy-pt').forEach(g => {
                const tag = g.getAttribute('data-tag');
                g.toggleAttribute('data-dim', active != null && tag !== active);
            });
        },

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

        get maxTimelineCount() {
            return Math.max(1, ...this.timeline.map(p => p.count));
        },

        barHeight(count) {
            return Math.round((count / this.maxTimelineCount) * 118);
        },

        // A bar with square baseline corners and rounded top corners (radius
        // clamped so it never exceeds the bar's own height or half its width).
        barPath(i, count) {
            const x = i * 32 + 6;
            const w = 20;
            const yBase = 120;
            const h = Math.max(this.barHeight(count), count > 0 ? 2 : 0);
            if (h === 0) return `M ${x} ${yBase} L ${x + w} ${yBase}`;
            const r = Math.min(4, h, w / 2);
            const y = yBase - h;
            return `M ${x} ${yBase} L ${x} ${y + r} Q ${x} ${y} ${x + r} ${y} `
                + `L ${x + w - r} ${y} Q ${x + w} ${y} ${x + w} ${y + r} L ${x + w} ${yBase} Z`;
        },

        // Alpine's x-for clones <template> content through the HTML parser,
        // which mishandles elements inside <svg> (wrong namespace, breaks
        // silently). Build the bars as a markup string instead and inject it
        // with x-html; hover feedback then comes from a CSS rule (.bar-mark)
        // plus event-delegated mouseover on the <svg> itself.
        get barsSvg() {
            const w = this.timeline.length * 32;
            const parts = [`<line x1="0" x2="${w}" y1="120" y2="120" stroke="#e1e0d9" stroke-width="1"></line>`];
            this.timeline.forEach((pt, i) => {
                parts.push(
                    `<path class="bar-mark" data-i="${i}" d="${this.barPath(i, pt.count)}">`
                    + `<title>${pt.label}: ${pt.count}</title></path>`
                );
            });
            return parts.join('');
        },

        onBarHover(event) {
            const el = event.target.closest('[data-i]');
            this.hoverIndex = el ? Number(el.dataset.i) : null;
        },

        // Thin out x-axis labels on long timelines so they don't collide.
        showLabel(i) {
            const n = this.timeline.length;
            if (n <= 12) return true;
            const step = Math.ceil(n / 12);
            return i % step === 0 || i === n - 1;
        },

        get maxTagCount() {
            return Math.max(1, ...this.topTags.map(t => t.count));
        },

        get maxDomainCount() {
            return Math.max(1, ...this.topDomains.map(d => d.count));
        },

        barWidth(count, max) {
            return Math.max(4, Math.round((count / max) * 100));
        },

        get minCloudCount() {
            return this.topTags.length ? Math.min(...this.topTags.map(t => t.count)) : 0;
        },

        cloudFontSize(count) {
            const min = this.minCloudCount, max = this.maxTagCount;
            const t = max === min ? 1 : (count - min) / (max - min);
            return Math.round(12 + t * 20); // 12px .. 32px
        },

        cloudColor(count) {
            const min = this.minCloudCount, max = this.maxTagCount;
            const t = max === min ? 1 : (count - min) / (max - min);
            if (t > 0.66) return 'text-indigo-700';
            if (t > 0.33) return 'text-indigo-500';
            return 'text-indigo-400';
        },
    }));
});
