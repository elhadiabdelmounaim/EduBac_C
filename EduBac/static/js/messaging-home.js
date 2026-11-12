(() => {
  const root = document.getElementById('messagingRoot');
  if (!root) return;

  const tabGroups = document.getElementById('messageTabGroups');
  const tabIndividuals = document.getElementById('messageTabIndividuals');
  const groupList = document.getElementById('groupList');
  const directList = document.getElementById('directList');
  const search = document.getElementById('messagingSearch');
  const classFilter = document.getElementById('classFilter');
  const unreadFilter = document.getElementById('unreadOnlyFilter');
  const emptyState = document.getElementById('messagingEmpty');
  const dialog = document.getElementById('newConversationDialog');
  const contactSearch = document.getElementById('contactSearch');
  const contactResults = document.getElementById('contactResults');
  const csrf = document.querySelector('#messagingCsrfForm [name="csrfmiddlewaretoken"]')?.value || '';
  let activeTab = 'groups';
  let contactTimer = null;
  let contactRequest = 0;

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

  function setTab(tab, updateUrl = true) {
    activeTab = tab === 'individuals' ? 'individuals' : 'groups';
    const individuals = activeTab === 'individuals';
    tabGroups.classList.toggle('is-active', !individuals);
    tabIndividuals.classList.toggle('is-active', individuals);
    tabGroups.setAttribute('aria-selected', String(!individuals));
    tabIndividuals.setAttribute('aria-selected', String(individuals));
    tabGroups.tabIndex = individuals ? -1 : 0;
    tabIndividuals.tabIndex = individuals ? 0 : -1;
    groupList.hidden = individuals;
    directList.hidden = !individuals;
    applyFilters();
    if (updateUrl) {
      const url = new URL(window.location.href);
      if (individuals) url.searchParams.set('tab', 'individuals');
      else url.searchParams.delete('tab');
      window.history.replaceState({}, '', url);
    }
  }

  function applyFilters() {
    const list = activeTab === 'individuals' ? directList : groupList;
    const query = (search.value || '').trim().toLowerCase();
    const selectedClass = classFilter.value;
    const unreadOnly = unreadFilter.checked;
    let visible = 0;
    list.querySelectorAll('.conversation-row').forEach((row) => {
      const matchesQuery = !query || (row.dataset.search || '').includes(query);
      const matchesClass = !selectedClass || row.dataset.classroomId === selectedClass;
      const matchesUnread = !unreadOnly || row.dataset.unread === '1';
      const show = matchesQuery && matchesClass && matchesUnread;
      row.hidden = !show;
      if (show) visible += 1;
    });
    const hasRows = list.querySelectorAll('.conversation-row').length > 0;
    emptyState.hidden = !hasRows || visible > 0;
  }

  function showContactMessage(message, className = 'contact-message') {
    contactResults.replaceChildren();
    const note = document.createElement('p');
    note.className = className;
    note.setAttribute('role', 'status');
    note.textContent = message;
    contactResults.append(note);
  }

  function renderContact(contact) {
    const row = document.createElement('div');
    row.className = 'contact-item';

    const avatar = document.createElement('span');
    avatar.className = `contact-avatar ${contact.kind === 'consultation' ? 'is-teacher' : ''}`;
    avatar.textContent = contact.avatar_letter || (contact.name || '?').slice(0, 1).toUpperCase();
    avatar.setAttribute('aria-hidden', 'true');

    const details = document.createElement('span');
    details.className = 'contact-item-details';
    const name = document.createElement('strong');
    name.textContent = contact.name || 'Contact EduBac';
    const subtitle = document.createElement('small');
    subtitle.textContent = contact.subtitle || (
      contact.kind === 'consultation' ? 'Professeur' : 'Conversation individuelle'
    );
    details.append(name, subtitle);

    if (contact.is_online) {
      const online = document.createElement('span');
      online.className = 'contact-online';
      online.textContent = 'En ligne';
      row.append(avatar, details, online);
    } else {
      row.append(avatar, details);
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'contact-start';
    button.textContent = 'Écrire';
    button.addEventListener('click', () => startConversation(contact, button));
    row.append(button);
    return row;
  }

  async function loadContacts() {
    const requestNumber = ++contactRequest;
    contactResults.setAttribute('aria-busy', 'true');
    showContactMessage('Recherche des contacts autorisés…', 'contact-loading-note');
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
        showContactMessage(
          query ? 'Aucun contact autorisé ne correspond à cette recherche.' : 'Aucun contact disponible pour le moment.',
        );
        return;
      }
      contacts.forEach((contact) => contactResults.append(renderContact(contact)));
    } catch (error) {
      if (requestNumber === contactRequest) showContactMessage(error.message);
    } finally {
      if (requestNumber === contactRequest) contactResults.setAttribute('aria-busy', 'false');
    }
  }

  async function startConversation(contact, button) {
    button.disabled = true;
    button.textContent = 'Ouverture…';
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
      button.disabled = false;
      button.textContent = 'Réessayer';
      showContactMessage(error.message);
    }
  }

  function openDialog() {
    if (!dialog.open) dialog.showModal();
    contactSearch.value = '';
    loadContacts();
    window.setTimeout(() => contactSearch.focus(), 0);
  }

  tabGroups.addEventListener('click', () => setTab('groups'));
  tabIndividuals.addEventListener('click', () => setTab('individuals'));
  document.getElementById('messageTabs').addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const nextTab = activeTab === 'groups' ? 'individuals' : 'groups';
    setTab(nextTab);
    (nextTab === 'groups' ? tabGroups : tabIndividuals).focus();
  });
  [search, classFilter, unreadFilter].forEach((control) => {
    control.addEventListener('input', applyFilters);
    control.addEventListener('change', applyFilters);
  });

  document.getElementById('newConversationBtn').addEventListener('click', openDialog);
  document.querySelectorAll('[data-open-contacts]').forEach((button) => {
    button.addEventListener('click', openDialog);
  });
  document.querySelectorAll('[data-close-dialog]').forEach((button) => {
    button.addEventListener('click', () => dialog.close());
  });
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
  contactSearch.addEventListener('input', () => {
    window.clearTimeout(contactTimer);
    contactTimer = window.setTimeout(loadContacts, 220);
  });
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      search.focus();
    }
  });

  const requestedTab = new URLSearchParams(window.location.search).get('tab')
    || root.dataset.activeTab;
  setTab(requestedTab === 'individuals' ? 'individuals' : 'groups', false);
})();
