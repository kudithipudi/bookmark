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

        async init() {
            const params = new URLSearchParams(window.location.search);
            if (params.get('search')) this.searchQuery = params.get('search');
            if (params.get('tag')) this.activeTag = params.get('tag');
            await this.loadBookmarks();
            await this.loadTags();
            // Deep-linked tag: bring its pill into view once rendered.
            this.$nextTick(() => {
                this.updateTagEdges();
                if (this.activeTag) {
                    const el = this.$refs.tagStrip?.querySelector('[data-active="yes"]');
                    if (el) this.focusTag(el, 'auto');
                }
            });
        },

        async loadBookmarks() {
            this.loading = true;
            const params = new URLSearchParams();
            if (this.searchQuery) params.set('search', this.searchQuery);
            if (this.activeTag) params.set('tag', this.activeTag);
            this.syncUrl();
            try {
                const resp = await fetch(`api/bookmarks?${params}`);
                this.bookmarks = await resp.json();
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
            history.replaceState(null, '', url.toString());
        },

        async loadTags() {
            try {
                const resp = await fetch('api/tags');
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
            this.loadBookmarks();
            this.focusTag(el);
        },

        clearTag(el) {
            this.activeTag = '';
            this.loadBookmarks();
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
                    await this.loadTags();
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
                    await this.loadTags();
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
                    await this.loadTags();
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
