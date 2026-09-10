document.addEventListener('alpine:init', () => {
    Alpine.data('bookmarkApp', () => ({
        bookmarks: [],
        tags: [],
        totalBookmarks: 0,
        // "Load more" pagination for the exact-match list. pageSize mirrors
        // the `limit` sent to api/bookmarks; offset advances by loadMore().
        // hasMore / totalMatches come from the X-Has-More / X-Total-Count
        // response headers on every fetch.
        pageSize: 60,
        offset: 0,
        hasMore: false,
        totalMatches: 0,
        // Set only during a "Load more" append. Kept separate from `loading`
        // so the existing results grid (gated on `!loading`) stays mounted
        // instead of flashing back to the skeleton on every page.
        loadingMore: false,
        // A page append failed. Pauses the scroll-triggered auto-load (so the
        // observer doesn't spin on a persistent error) until the user hits
        // "Retry".
        loadError: false,
        newUrl: '',
        searchQuery: '',
        activeTag: '',
        adding: false,
        loading: true,
        editingId: null,
        editForm: { title: '', description: '', tags: '' },
        deleteModal: { open: false, id: null, password: '', error: '' },
        toast: { msg: '', type: 'success' },
        tagEdges: { left: false, right: false },
        // Link-health filter: '' (all), 'broken', or 'review'. Mutually
        // exclusive with a tag filter (see the $watch in init()).
        healthFilter: '',
        linkHealth: { broken: 0, review: 0, checked: 0, total: 0, last_run: null },
        linkCheck: { open: false, password: '', error: '', running: false, run: null, poll: null },
        // Consecutive failed sweeps before a link is called "broken" (mirrors
        // LINK_CHECK_BROKEN_THRESHOLD on the server).
        brokenThreshold: 1,

        // Search-results constellation: id of the semantic result currently
        // hovered or focused, mirrored between its card and its star.
        hoveredId: null,

        async init() {
            const params = new URLSearchParams(window.location.search);
            if (params.get('search')) this.searchQuery = params.get('search');
            if (params.get('tag')) this.activeTag = params.get('tag');
            if (['broken', 'review'].includes(params.get('health'))) {
                this.healthFilter = params.get('health');
            }
            // A tag filter and a link-health filter can't both be active.
            this.$watch('activeTag', v => { if (v) this.healthFilter = ''; });
            await this.loadBookmarks();
            this.loadLinkHealth();
            // Infinite scroll: when the sentinel at the end of the list comes
            // near the viewport, pull the next page. The 400px margin starts
            // the fetch just before the user reaches the bottom. loadMore()'s
            // own guards keep overlapping/exhausted/errored loads from firing.
            this._pageObserver = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting) this.loadMore();
            }, { rootMargin: '400px 0px' });
            // Deep-linked tag: bring its pill into view once rendered.
            this.$nextTick(() => {
                if (this.$refs.infiniteSentinel) {
                    this._pageObserver.observe(this.$refs.infiniteSentinel);
                }
                this.updateTagEdges();
                if (this.activeTag) {
                    const el = this.$refs.tagStrip?.querySelector('[data-active="yes"]');
                    if (el) this.focusTag(el, 'auto');
                }
            });
        },

        async loadBookmarks(scroll = false, append = false) {
            // Filter changes (tag/search) can shrink a long, scrolled-down
            // list — snap back to the top so the new results aren't hidden
            // below the fold. Mutations (add/edit/delete) skip this so the
            // page doesn't jump away from where the user was working.
            if (scroll) window.scrollTo(0, 0);
            // Append keeps the results grid on screen (loadingMore); a fresh
            // load swaps in the skeleton (loading).
            if (append) this.loadingMore = true;
            else this.loading = true;
            // Non-append fetches (any filter change or post-mutation reload)
            // restart at page 0. Append keeps the offset loadMore() advanced.
            if (!append) this.offset = 0;
            const params = new URLSearchParams();
            if (this.searchQuery) params.set('search', this.searchQuery);
            if (this.activeTag) params.set('tag', this.activeTag);
            if (this.healthFilter) params.set('status', this.healthFilter);
            params.set('limit', this.pageSize);
            params.set('offset', this.offset);
            this.syncUrl();
            try {
                // Tag list is fetched alongside, scoped to the same search text,
                // so the sidebar always reflects what's actually on screen.
                const [bmResp] = await Promise.all([
                    fetch(`api/bookmarks?${params}`),
                    this.loadTags(),
                ]);
                const rows = await bmResp.json();
                // Semantic rows only arrive on page 0, so append pages carry
                // exact matches only — concatenating is safe.
                this.bookmarks = append ? [...this.bookmarks, ...rows] : rows;
                this.hasMore = bmResp.headers.get('X-Has-More') === 'true';
                this.totalMatches = parseInt(bmResp.headers.get('X-Total-Count') || '0', 10);
                if (!append) this.loadError = false;
            } catch (e) {
                // Roll back the optimistic bump so the next loadMore() re-requests
                // this page instead of skipping it.
                if (append) {
                    this.offset = Math.max(0, this.offset - this.pageSize);
                    this.loadError = true;
                }
                this.showToast('Failed to load bookmarks. Try refreshing.', 'error');
            }
            this.loading = false;
            this.loadingMore = false;
        },

        // Pull the next page and append it. Fired by the scroll sentinel and
        // the manual button; guarded so overlapping, exhausted, or errored
        // loads can't stack.
        loadMore() {
            if (this.loading || this.loadingMore || this.loadError || !this.hasMore) return;
            this.offset += this.pageSize;
            this.loadBookmarks(false, true);
        },

        // "Retry" after a failed append: clear the error gate and try again.
        retryLoadMore() {
            this.loadError = false;
            this.loadMore();
        },

        syncUrl() {
            const url = new URL(window.location.href);
            if (this.searchQuery) url.searchParams.set('search', this.searchQuery);
            else url.searchParams.delete('search');
            if (this.activeTag) url.searchParams.set('tag', this.activeTag);
            else url.searchParams.delete('tag');
            if (this.healthFilter) url.searchParams.set('health', this.healthFilter);
            else url.searchParams.delete('health');
            history.replaceState(null, '', url.toString());
        },

        async loadTags() {
            try {
                const params = new URLSearchParams();
                if (this.searchQuery) params.set('search', this.searchQuery);
                const resp = await fetch(`api/tags?${params}`);
                const data = await resp.json();
                this.tags = data.tags || [];
                this.totalBookmarks = data.total || 0;
            } catch (e) {}
            this.$nextTick(() => this.updateTagEdges());
        },

        // Mobile tag strip: track whether off-screen pills exist on either
        // side so the fade overlays can hint at hidden content.
        updateTagEdges() {
            const el = this.$refs.tagStrip;
            if (!el) return;
            this.tagEdges.left = el.scrollLeft > 4;
            this.tagEdges.right =
                el.scrollWidth > el.clientWidth + 4 &&
                el.scrollLeft < el.scrollWidth - el.clientWidth - 4;
        },

        focusTag(el, behavior = 'smooth') {
            el?.scrollIntoView({ behavior, inline: 'center', block: 'nearest' });
            this.$nextTick(() => this.updateTagEdges());
        },

        pickTag(tag, el) {
            this.activeTag = tag;
            this.loadBookmarks(true);
            this.focusTag(el);
        },

        clearTag(el) {
            this.activeTag = '';
            this.loadBookmarks(true);
            this.focusTag(el);
        },

        // Search splits into two visual sections: keyword matches, then
        // embedding-based recommendations under their own heading.
        get exactBookmarks() {
            return this.bookmarks.filter(b => b.match !== 'semantic');
        },

        get semanticBookmarks() {
            return this.bookmarks.filter(b => b.match === 'semantic');
        },

        matchPercent(score) {
            return Math.round((score || 0) * 100);
        },

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
        //
        // Deliberately does NOT read hoveredId: x-html replaces the whole
        // subtree whenever this getter's dependencies change, which would
        // recreate every node on each hover (killing the CSS transitions and
        // restarting the twinkle animation). Hover is applied to the already
        // rendered nodes by applyConstellationHot() instead.
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
                const jitter = (((Math.imul(b.id, 2654435761) >>> 0) % 1000) / 1000 - 0.5) * 0.28;
                const ang = base + i * step + jitter;
                const x = +(CX + (RX_MAX - t * (RX_MAX - RX_MIN)) * Math.cos(ang)).toFixed(1);
                const y = +(CY + (RY_MAX - t * (RY_MAX - RY_MIN)) * Math.sin(ang)).toFixed(1);
                const dot = +(2 + t * 2.8).toFixed(1);
                const lineOpacity = +(0.1 + t * 0.32).toFixed(2);
                const labelY = Math.sin(ang) >= -0.2
                    ? +(y + dot + 11).toFixed(1)
                    : +(y - dot - 6).toFixed(1);
                return `<g class="star-g" data-id="${b.id}">`
                    + `<line class="star-line" x1="${CX}" y1="${CY}" x2="${x}" y2="${y}" stroke="#6366f1" stroke-opacity="${lineOpacity}" stroke-width="1"></line>`
                    + `<circle class="star-dot" cx="${x}" cy="${y}" r="${dot}" fill="#6366f1" style="animation-delay:-${(b.id % 7) * 0.5}s"></circle>`
                    + `<text class="star-label" x="${x}" y="${labelY}" text-anchor="middle" fill="#4f46e5" style="font-size:9px;font-weight:600">${this.escapeXml(this.starLabel(b.title || b.url))}</text>`
                    + `</g>`;
            }).join('');

            const q = this.searchQuery.trim();
            const caption = q.length > 40 ? q.slice(0, 39).trimEnd() + '…' : q;
            // The caption sits above the star band (y ∈ [CY-RY_MAX, CY+RY_MAX]
            // = [28, 168]) so no star or connector line can run through it.
            const center = `<circle cx="${CX}" cy="${CY}" r="5.5" fill="#4f46e5"></circle>`
                + `<circle cx="${CX}" cy="${CY}" r="10" fill="none" stroke="#4f46e5" stroke-opacity="0.3" stroke-width="1.5"></circle>`
                + `<text x="${CX}" y="18" text-anchor="middle" fill="#64748b" style="font-size:10px;font-weight:600">“${this.escapeXml(caption)}”</text>`;

            // Soft glow behind the query node (spec's render order: rings,
            // halo, stars, center). The gradient id is namespaced so it can
            // never collide with another inline-SVG gradient on the page.
            const halo = `<defs><radialGradient id="constellationStarHalo">`
                + `<stop offset="0%" stop-color="#6366f1" stop-opacity="0.16"></stop>`
                + `<stop offset="100%" stop-color="#6366f1" stop-opacity="0"></stop>`
                + `</radialGradient></defs>`
                + `<circle cx="${CX}" cy="${CY}" r="70" fill="url(#constellationStarHalo)"></circle>`;

            return rings + halo + stars + center;
        },

        // Toggle .is-hot on the already-rendered stars. Driven by x-effect on
        // the banner <svg>, which re-runs whenever hoveredId changes and once
        // after each x-html render, so the CSS transitions actually tween.
        applyConstellationHot() {
            const svg = this.$refs.constellationSvg;
            if (!svg) return;
            // Touch the result list too so this effect re-runs after x-html
            // repaints the stars, not only on hover. x-html is bound first
            // (same attribute bucket, earlier in the tag), so it repaints
            // before this runs; if it ever ran first the fresh nodes would
            // still come out with no .is-hot, which is the same end state.
            void this.semanticBookmarks.length;
            const hot = this.hoveredId;
            svg.querySelectorAll('.star-g').forEach(g => {
                g.classList.toggle('is-hot', Number(g.dataset.id) === hot);
            });
        },

        constellationHover(event) {
            const g = event.target.closest('[data-id]');
            this.hoveredId = g ? Number(g.dataset.id) : null;
        },

        constellationClick(event) {
            const g = event.target.closest('[data-id]');
            if (g) this.scrollCardIntoView(Number(g.dataset.id));
        },

        async addBookmark() {
            if (!this.newUrl) return;
            if (!/^https?:\/\//i.test(this.newUrl)) {
                this.newUrl = 'https://' + this.newUrl;
            }
            this.adding = true;
            try {
                const resp = await fetch('api/bookmarks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: this.newUrl })
                });
                if (resp.status === 409) {
                    this.showToast('This URL is already saved', 'error');
                } else if (resp.ok) {
                    this.newUrl = '';
                    await this.loadBookmarks();
                    this.showToast('Bookmark saved');
                } else {
                    this.showToast('Failed to save bookmark', 'error');
                }
            } catch (e) {
                this.showToast('Failed to save bookmark', 'error');
            }
            this.adding = false;
        },

        startEdit(bm) {
            this.editingId = bm.id;
            this.editForm = {
                title: bm.title || '',
                description: bm.description || '',
                tags: bm.tags || ''
            };
        },

        async saveEdit(id) {
            try {
                const resp = await fetch(`api/bookmarks/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.editForm)
                });
                if (resp.ok) {
                    this.editingId = null;
                    await this.loadBookmarks();
                    this.showToast('Bookmark updated');
                }
            } catch (e) {
                this.showToast('Failed to update', 'error');
            }
        },

        openDeleteModal(id) {
            this.deleteModal = { open: true, id, password: '', error: '' };
            this.$nextTick(() => this.$refs.deletePasswordInput?.focus());
        },

        // --- Link health ---------------------------------------------------

        async loadLinkHealth() {
            try {
                const resp = await fetch('api/link-health');
                if (resp.ok) this.linkHealth = await resp.json();
            } catch (e) {}
        },

        pickHealth(filter) {
            this.healthFilter = this.healthFilter === filter ? '' : filter;
            if (this.healthFilter) this.activeTag = '';
            this.loadBookmarks(true);
        },

        // Red badge only once a link has failed the threshold; before that
        // it's amber "failing" (could still be a transient blip).
        linkBadge(bm) {
            const s = bm.link_status;
            if (!s || s === 'ok') return null;
            const code = bm.link_status_code ? ' · ' + bm.link_status_code : '';
            if (s === 'broken') {
                const confirmed = (bm.link_fail_count || 0) >= this.brokenThreshold;
                return {
                    cls: confirmed
                        ? 'bg-rose-50 text-rose-700 border-rose-200'
                        : 'bg-amber-50 text-amber-800 border-amber-200',
                    label: (confirmed ? 'Link broken' : 'Link failing') + code,
                };
            }
            if (s === 'moved') {
                return { cls: 'bg-amber-50 text-amber-800 border-amber-200', label: 'Redirects elsewhere' };
            }
            return { cls: 'bg-slate-100 text-slate-600 border-slate-200', label: 'Unreachable' + code };
        },

        async adoptFinalUrl(bm) {
            if (!bm.link_final_url) return;
            try {
                const resp = await fetch(`api/bookmarks/${bm.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: bm.link_final_url }),
                });
                if (resp.status === 409) {
                    this.showToast('That URL is already saved', 'error');
                } else if (resp.ok) {
                    await Promise.all([this.loadBookmarks(), this.loadLinkHealth()]);
                    this.showToast('URL updated');
                } else {
                    this.showToast('Failed to update URL', 'error');
                }
            } catch (e) {
                this.showToast('Failed to update URL', 'error');
            }
        },

        // --- Bulk link check ---------------------------------------------------

        openLinkCheck() {
            this.linkCheck.open = true;
            this.linkCheck.error = '';
            const run = this.linkHealth.last_run;
            if (run && !run.finished_at) {
                // A sweep is already running (maybe from another tab) — attach.
                this.linkCheck.run = run;
                this.linkCheck.running = true;
                this.startLinkCheckPolling();
            } else if (!this.linkCheck.running) {
                this.linkCheck.run = null;
            }
            this.$nextTick(() => this.$refs.linkCheckPassword?.focus());
        },

        get linkCheckProgress() {
            const r = this.linkCheck.run;
            if (!r || !r.total) return 0;
            return Math.round((r.checked / r.total) * 100);
        },

        async fetchLinkCheckRun() {
            try {
                const resp = await fetch('api/admin/link-check', {
                    headers: { 'X-Admin-Password': this.linkCheck.password },
                });
                if (resp.ok) return (await resp.json()).run;
            } catch (e) {}
            return null;
        },

        async startLinkCheck() {
            if (!this.linkCheck.password || this.linkCheck.running) return;
            this.linkCheck.error = '';
            this.linkCheck.running = true;
            try {
                const resp = await fetch('api/admin/link-check', {
                    method: 'POST',
                    headers: { 'X-Admin-Password': this.linkCheck.password },
                });
                if (resp.status === 401) {
                    this.linkCheck.running = false;
                    this.linkCheck.error = 'Incorrect password. Try again.';
                    this.linkCheck.password = '';
                    this.$nextTick(() => this.$refs.linkCheckPassword?.focus());
                    return;
                }
                if (resp.status === 409) {
                    this.linkCheck.run = await this.fetchLinkCheckRun();
                    this.startLinkCheckPolling();
                    return;
                }
                if (!resp.ok) {
                    this.linkCheck.running = false;
                    this.linkCheck.error = 'Something went wrong. Try again.';
                    return;
                }
                this.linkCheck.run = await resp.json();
                this.startLinkCheckPolling();
            } catch (e) {
                this.linkCheck.running = false;
                this.linkCheck.error = 'Something went wrong. Try again.';
            }
        },

        startLinkCheckPolling() {
            this.stopLinkCheckPolling();
            this.linkCheck.poll = setInterval(async () => {
                const run = await this.fetchLinkCheckRun();
                if (run) this.linkCheck.run = run;
                if (!run || run.finished_at) {
                    this.stopLinkCheckPolling();
                    this.linkCheck.running = false;
                    await Promise.all([this.loadBookmarks(), this.loadLinkHealth()]);
                    if (run && run.error) {
                        this.showToast('Link check failed. See the logs.', 'error');
                    } else if (run) {
                        this.showToast(
                            `Link check done — ${run.broken} broken, ${run.moved} moved, ${run.uncertain} unreachable`
                        );
                    }
                }
            }, 2000);
        },

        stopLinkCheckPolling() {
            if (this.linkCheck.poll) {
                clearInterval(this.linkCheck.poll);
                this.linkCheck.poll = null;
            }
        },

        async confirmDelete() {
            if (!this.deleteModal.password) return;
            try {
                const resp = await fetch(`api/bookmarks/${this.deleteModal.id}`, {
                    method: 'DELETE',
                    headers: { 'X-Delete-Password': this.deleteModal.password }
                });
                if (resp.ok) {
                    this.deleteModal.open = false;
                    await this.loadBookmarks();
                    this.showToast('Bookmark deleted');
                } else if (resp.status === 401) {
                    this.deleteModal.error = 'Incorrect password. Try again.';
                    this.deleteModal.password = '';
                    this.$nextTick(() => this.$refs.deletePasswordInput?.focus());
                } else {
                    this.deleteModal.error = 'Something went wrong. Try again.';
                }
            } catch (e) {
                this.deleteModal.error = 'Something went wrong. Try again.';
            }
        },

        showToast(msg, type = 'success') {
            this.toast = { msg, type };
            setTimeout(() => { this.toast = { msg: '', type: 'success' }; }, 3000);
        }
    }));
});
