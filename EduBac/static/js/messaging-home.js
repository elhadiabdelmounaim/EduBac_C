/**
 * Liste des discussions (accueil, salon de classe, conversation privée) :
 * filtres, recherche, heures relatives et fenêtre « Nouveau message ».
 */
(() => {
  const root = document.getElementById('messagingRoot');
  if (!root) return;

  const Chat = window.EduBacChat || null;
  const chips = Array.from(document.querySelectorAll('#messageTabs [data-filter]'));
  const list = document.getElementById('threadList');
  const search = document.getElementById('messagingSearch');
  const classFilter = document.getElementById('classFilter');
  const emptyState = document.getElementById('messagingEmpty');
  const dialog = document.getElementById('newConversationDialog');
  const contactSearch = document.getElementById('contactSearch');
  const contactResults = document.getElementById('contactResults');
  const csrf = document.querySelector('#messagingCsrfForm [name="csrfmiddlewaretoken"]')?.value || '';
  const FILTERS = ['all', 'unread', 'groups', 'individuals'];
  let activeFilter = 'all';
  let contactTimer = null;
  let contactRequest = 0;

  /* ---- Hauteur disponible sous la barre de navigation (mobile compris) ---- */
  const navbar = document.querySelector('.edubac-navbar');
  function fitHeight() {
    const top = navbar ? navbar.getBoundingClientRect().height : 64;
    document.documentElement.style.setProperty('--chat-top', `${Math.round(top)}px`);
  }
  fitHeight();
  window.addEventListener('resize', fitHeight, { passive: true });

  /* ---- Présentation : avatars et heures ---- */
  if (Chat) Chat.paintAvatars(root);
  if (Chat) Chat.paintAvatars(document.querySelector('.chat-main-header') || undefined);
  function refreshTimes() {
    if (!Chat) return;
    root.querySelectorAll('.chat-thread-time[datetime]').forEach((time) => {
      const label = Chat.listTimeLabel(time.getAttribute('datetime'));
      if (label) time.textContent = label;
    });
  }
  refreshTimes();
  window.setInterval(refreshTimes, 60000);

  // La conversation ouverte est lue : on retire son badge.
  const active = list && list.querySelector('.chat-thread.is-active');
  if (active) {
    active.dataset.unread = '0';
    active.classList.remove('has-unread');
    active.querySelector('.chat-unread')?.remove();
    active.scrollIntoView({ block: 'nearest' });
  }

  /* ---- Filtres ---- */
  function applyFilters() {
    if (!list) return;
    const query = (search.value || '').trim().toLowerCase();
    const selectedClass = classFilter ? classFilter.value : '';
    const rows = list.querySelectorAll('.chat-thread');
    let visible = 0;
    rows.forEach((row) => {
      const kind = row.dataset.kind;
      const matchesFilter = activeFilter === 'all'
        || (activeFilter === 'unread' && row.dataset.unread === '1')
        || (activeFilter === 'groups' && kind === 'class')
        || (activeFilter === 'individuals' && kind !== 'class');
      const show = matchesFilter
        && (!query || (row.dataset.search || '').includes(query))
        && (!selectedClass || row.dataset.classroomId === selectedClass);
      row.hidden = !show;
      if (show) visible += 1;
    });
    if (emptyState) emptyState.hidden = !rows.length || visible > 0;
  }

  function setFilter(filter, updateUrl = true) {
    activeFilter = FILTERS.includes(filter) ? filter : 'all';
    chips.forEach((chip) => {
      chip.setAttribute('aria-pressed', String(chip.dataset.filter === activeFilter));
    });
    applyFilters();
    if (updateUrl && !root.dataset.activeThread) {
      const url = new URL(window.location.href);
      if (activeFilter === 'all') url.searchParams.delete('tab');
      else url.searchParams.set('tab', activeFilter);
      window.history.replaceState({}, '', url);
    }
  }

  chips.forEach((chip) => chip.addEventListener('click', () => setFilter(chip.dataset.filter)));
  if (search) search.addEventListener('input', applyFilters);
  if (classFilter) classFilter.addEventListener('change', applyFilters);
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && search) {
      event.preventDefault();
      search.focus();
    }
  });

  /* ---- Fenêtre « Nouveau message » ---- */
  async function jsonResponse(response, fallback) {
    const contentType = (response.headers.get('content-type') || '').toLowerCase();
    if (!contentType.includes('application/json')) {
      throw new Error(response.redirected
        ? 'Votre session a expiré. Reconnectez-vous puis réessayez.'
        : 'Réponse inattendue du serveur. Actualisez la page et réessayez.');
    }
    let data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error('Réponse invalide du serveur. Actualisez la page et réessayez.');
    }
    if (!response.ok) throw new Error(data.error || fallback);
    return data;
  }

  function showContactMessage(message) {
    contactResults.replaceChildren();
    const note = document.createElement('p');
    note.className = 'contact-message';
    note.setAttribute('role', 'status');
    note.textContent = message;
    contactResults.append(note);
  }

  function renderContact(contact) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'contact-item';

    const avatar = document.createElement('span');
    avatar.className = 'chat-avatar';
    avatar.textContent = contact.avatar_letter || (contact.name || '?').slice(0, 1).toUpperCase();
    avatar.setAttribute('aria-hidden', 'true');
    if (Chat) avatar.dataset.tone = String(Chat.avatarTone(contact.name));
    if (contact.is_online) {
      const dot = document.createElement('span');
      dot.className = 'chat-presence-dot';
      avatar.append(dot);
    }

    const details = document.createElement('span');
    details.className = 'contact-item-details';
    const name = document.createElement('strong');
    name.textContent = contact.name || 'Contact EduBac';
    const subtitle = document.createElement('small');
    subtitle.textContent = (contact.is_online ? 'En ligne · ' : '') + (contact.subtitle || (
      contact.kind === 'consultation' ? 'Professeur' : 'Conversation individuelle'
    ));
    details.append(name, subtitle);

    const action = document.createElement('span');
    action.className = 'contact-start';
    action.textContent = 'Écrire';
    row.append(avatar, details, action);
    row.addEventListener('click', () => startConversation(contact, row, action));
    return row;
  }

  async function loadContacts() {
    const requestNumber = ++contactRequest;
    contactResults.setAttribute('aria-busy', 'true');
    showContactMessage('Recherche des contacts autorisés…');
    const url = new URL(root.dataset.contactsUrl, window.location.origin);
    const query = (contactSearch.value || '').trim();
    if (query) url.searchParams.set('q', query);
    try {
      const response = await fetch(url, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      const data = await jsonResponse(response, 'Impossible de charger les contacts.');
      if (requestNumber !== contactRequest) return;
      const contacts = data.contacts || [];
      contactResults.replaceChildren();
      if (!contacts.length) {
        showContactMessage(query
          ? 'Aucun contact autorisé ne correspond à cette recherche.'
          : 'Aucun contact disponible pour le moment.');
        return;
      }
      contacts.forEach((contact) => contactResults.append(renderContact(contact)));
    } catch (error) {
      if (requestNumber === contactRequest) showContactMessage(error.message);
    } finally {
      if (requestNumber === contactRequest) contactResults.setAttribute('aria-busy', 'false');
    }
  }

  async function startConversation(contact, row, label) {
    row.disabled = true;
    label.textContent = 'Ouverture…';
    try {
      const response = await fetch(root.dataset.startUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf,
          Accept: 'application/json',
        },
        body: JSON.stringify({
          user_id: contact.id,
          classroom_id: contact.classroom_id || null,
        }),
      });
      const data = await jsonResponse(response, 'Impossible de démarrer cette conversation.');
      if (!data.url) throw new Error('Lien de conversation manquant.');
      window.location.assign(data.url);
    } catch (error) {
      row.disabled = false;
      label.textContent = 'Réessayer';
      showContactMessage(error.message);
    }
  }

  function openDialog() {
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    contactSearch.value = '';
    loadContacts();
    window.setTimeout(() => contactSearch.focus(), 0);
  }

  document.getElementById('newConversationBtn')?.addEventListener('click', openDialog);
  document.querySelectorAll('[data-open-contacts]').forEach((button) => {
    button.addEventListener('click', openDialog);
  });
  if (dialog) {
    dialog.querySelectorAll('[data-close-dialog]').forEach((button) => {
      button.addEventListener('click', () => dialog.close());
    });
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
  }
  if (contactSearch) {
    contactSearch.addEventListener('input', () => {
      window.clearTimeout(contactTimer);
      contactTimer = window.setTimeout(loadContacts, 220);
    });
  }

  const requested = new URLSearchParams(window.location.search).get('tab')
    || (root.dataset.activeTab === 'individuals' ? 'individuals' : 'all');
  setFilter(requested, false);
})();
