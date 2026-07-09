document.addEventListener('alpine:init', () => {
    Alpine.data('bookmarkApp', () => ({
        bookmarks: [],
        tags: [],
        newUrl: '',
        searchQuery: '',
        activeTag: '',
        adding: false,
        loading: true,
        editingId: null,
        editForm: { title: '', description: '', tags: '' },
        deleteModal: { open: false, id: null, password: '', error: '' },
        toast: { msg: '', type: 'success' },

        async init() {
            await this.loadBookmarks();
            await this.loadTags();
        },

        async loadBookmarks() {
            this.loading = true;
            const params = new URLSearchParams();
            if (this.searchQuery) params.set('search', this.searchQuery);
            if (this.activeTag) params.set('tag', this.activeTag);
            try {
                const resp = await fetch(`api/bookmarks?${params}`);
                this.bookmarks = await resp.json();
            } catch (e) {
                this.showToast('Failed to load bookmarks', 'error');
            }
            this.loading = false;
        },

        async loadTags() {
            try {
                const resp = await fetch('api/tags');
                this.tags = await resp.json();
            } catch (e) {}
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
