document.addEventListener('alpine:init', () => {
    Alpine.data('bookmarkApp', () => ({
        bookmarks: [],
        tags: [],
        totalBookmarks: 0,
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
            // Deep-linked tag: bring its pill into view once rendered.
            this.$nextTick(() => {
                this.updateTagEdges();
                if (this.activeTag) {
                    const el = this.$refs.tagStrip?.querySelector('[data-active="yes"]');
                    if (el) this.focusTag(el, 'auto');
                }
            });
        },

        async loadBookmarks(scroll = false) {
            // Filter changes (tag/search) can shrink a long, scrolled-down
            // list — snap back to the top so the new results aren't hidden
            // below the fold. Mutations (add/edit/delete) skip this so the
            // page doesn't jump away from where the user was working.
            if (scroll) window.scrollTo(0, 0);
            this.loading = true;
            const params = new URLSearchParams();
            if (this.searchQuery) params.set('search', this.searchQuery);
            if (this.activeTag) params.set('tag', this.activeTag);
            if (this.healthFilter) params.set('status', this.healthFilter);
            this.syncUrl();
            try {
                // Tag list is fetched alongside, scoped to the same search text,
                // so the sidebar always reflects what's actually on screen.
                const [bmResp] = await Promise.all([
                    fetch(`api/bookmarks?${params}`),
                    this.loadTags(),
                ]);
                this.bookmarks = await bmResp.json();
            } catch (e) {
                this.showToast('Failed to load bookmarks. Try refreshing.', 'error');
            }
            this.loading = false;
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
