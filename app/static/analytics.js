document.addEventListener('alpine:init', () => {
    Alpine.data('analyticsApp', () => ({
        loading: true,
        totals: { total_bookmarks: 0, total_tags: 0, total_domains: 0, added_this_month: 0 },
        timeline: [],
        topTags: [],
        topDomains: [],
        hoverIndex: null,

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
