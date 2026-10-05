/**
 * EduBac — Notifications temps réel (polling léger)
 */
(function () {
    const cfg = window.EDUBAC_NOTIF;
    if (!cfg) return;

    const badge = document.getElementById('notifBadge');
    const listEl = document.getElementById('notifList');
    const emptyEl = document.getElementById('notifEmpty');
    const markAllBtn = document.getElementById('notifMarkAllRead');
    const bellBtn = document.getElementById('notifBellBtn');

    let lastUnread = -1;

    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? match[2] : cfg.csrfToken;
    }

    function updateBadge(count) {
        if (!badge) return;
        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : String(count);
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }
        // Animation légère si nouveau message
        if (lastUnread >= 0 && count > lastUnread && bellBtn) {
            bellBtn.classList.add('notif-pulse');
            setTimeout(function () { bellBtn.classList.remove('notif-pulse'); }, 800);
        }
        lastUnread = count;
    }

    function iconForType(type) {
        const map = {
            quiz_assigned: 'bi-clipboard-check',
            quiz_result: 'bi-bar-chart',
            classroom: 'bi-people',
            lesson: 'bi-journal-text',
            ai: 'bi-robot',
            system: 'bi-info-circle',
        };
        return map[type] || 'bi-bell';
    }

    function renderList(notifications) {
        if (!listEl) return;
        if (!notifications.length) {
            listEl.innerHTML =
                '<div class="px-3 py-4 text-center text-muted small">Aucune notification pour le moment.</div>';
            return;
        }
        listEl.innerHTML = notifications.map(function (n) {
            const unreadClass = n.is_read ? '' : ' notif-unread';
            const href = n.link || '#';
            return (
                '<a href="' + href + '" class="notif-item d-flex gap-2 px-3 py-2 text-decoration-none text-dark' + unreadClass + '" data-id="' + n.id + '">' +
                    '<div class="notif-icon"><i class="bi ' + iconForType(n.type) + '"></i></div>' +
                    '<div class="flex-grow-1 min-width-0">' +
                        '<div class="fw-semibold small text-truncate">' + escapeHtml(n.title) + '</div>' +
                        '<div class="text-muted small text-truncate">' + escapeHtml(n.message) + '</div>' +
                        '<div class="text-muted" style="font-size:0.7rem">' + escapeHtml(n.time_ago) + '</div>' +
                    '</div>' +
                    (n.is_read ? '' : '<span class="notif-dot align-self-center"></span>') +
                '</a>'
            );
        }).join('');

        listEl.querySelectorAll('.notif-item').forEach(function (el) {
            el.addEventListener('click', function () {
                const id = el.getAttribute('data-id');
                if (id) markRead(id);
            });
        });
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    function fetchList() {
        return fetch(cfg.listUrl + '?limit=15', {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                updateBadge(data.unread_count || 0);
                renderList(data.notifications || []);
            })
            .catch(function () {
                if (listEl && listEl.querySelector('#notifEmpty')) {
                    listEl.innerHTML =
                        '<div class="px-3 py-3 text-center text-muted small">Impossible de charger les notifications.</div>';
                }
            });
    }

    function fetchCount() {
        return fetch(cfg.countUrl, {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' },
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                updateBadge(data.unread_count || 0);
            })
            .catch(function () { /* silencieux */ });
    }

    function removeNotifFromList(id) {
        if (!listEl) return;
        var el = listEl.querySelector('.notif-item[data-id="' + id + '"]');
        if (el) el.remove();
        if (!listEl.querySelector('.notif-item')) {
            listEl.innerHTML =
                '<div class="px-3 py-4 text-center text-muted small">Aucune notification pour le moment.</div>';
        }
    }

    function markRead(id) {
        const url = cfg.markReadUrlTemplate.replace('{id}', id);
        removeNotifFromList(id);
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
                'Accept': 'application/json',
            },
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (typeof data.unread_count === 'number') {
                    updateBadge(data.unread_count);
                } else {
                    fetchCount();
                }
            })
            .catch(function () { fetchList(); });
    }

    function markAllRead() {
        return fetch(cfg.markAllUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
                'Accept': 'application/json',
            },
        })
            .then(function (r) { return r.json(); })
            .then(function () {
                updateBadge(0);
                if (listEl) {
                    listEl.innerHTML =
                        '<div class="px-3 py-4 text-center text-muted small">Aucune notification pour le moment.</div>';
                }
            });
    }

    if (markAllBtn) {
        markAllBtn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            markAllRead();
        });
    }

    // Charger dès l'ouverture du menu
    if (bellBtn) {
        bellBtn.addEventListener('click', function () {
            fetchList();
        });
    }

    // Premier chargement + polling
    fetchList();
    setInterval(fetchCount, cfg.pollIntervalMs || 15000);

    // Rafraîchir la liste quand l'onglet redevient visible
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) fetchCount();
    });
})();
