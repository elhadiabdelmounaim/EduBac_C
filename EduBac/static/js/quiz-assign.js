/** Affectation d'un quiz importé : choix de la classe puis confirmation. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('sendQuizForm');
    if (!form) return;
    var dialog = document.getElementById('assignConfirm');
    var errorBox = document.getElementById('assignError');
    var confirmButton = document.getElementById('assignConfirmBtn');
    var confirmed = false;
    var text = document.getElementById('assignConfirmText');
    var title = (document.getElementById('quiz-preview-title') || {}).textContent || 'ce quiz';

    function showError(message) {
      if (!errorBox) { window.alert(message); return; }
      errorBox.textContent = message;
      errorBox.hidden = false;
      if (errorBox.scrollIntoView) errorBox.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    function markChecked() {
      Array.prototype.forEach.call(form.querySelectorAll('.qb-class-card'), function (card) {
        var input = card.querySelector('input');
        card.classList.toggle('is-checked', !!(input && input.checked));
      });
    }
    var label = document.getElementById('assignQuizLabel');
    function checkedClasses() {
      return Array.prototype.slice.call(form.querySelectorAll('input[name="classroom"]:checked:not(:disabled)'));
    }
    function updateLabel() {
      if (!label) return;
      var n = checkedClasses().length;
      label.textContent = n > 1 ? 'Affecter le quiz à ces ' + n + ' classes' : 'Affecter le quiz à cette classe';
    }
    markChecked();
    updateLabel();
    form.addEventListener('change', function () { if (errorBox) errorBox.hidden = true; markChecked(); updateLabel(); });

    function submitNow() {
      confirmed = true;
      if (confirmButton) { confirmButton.disabled = true; confirmButton.textContent = 'Affectation…'; }
      HTMLFormElement.prototype.submit.call(form);
    }

    // Les cases sont invisibles (cartes) : le navigateur ne peut pas afficher
    // son avertissement, on explique donc nous-mêmes pourquoi rien ne part.
    form.setAttribute('novalidate', '');
    form.addEventListener('submit', function (event) {
      if (confirmed) return;
      event.preventDefault();
      var radios = form.querySelectorAll('input[name="classroom"]');
      var enabled = Array.prototype.filter.call(radios, function (r) { return !r.disabled; });
      var chosen = checkedClasses();
      if (!radios.length) { showError('Vous n’avez encore aucune classe : créez-en une, puis revenez affecter ce quiz.'); return; }
      if (!enabled.length) {
        showError('Aucune de vos classes ne peut recevoir ce quiz : elles sont d’un autre niveau ou n’ont aucun élève inscrit (voir la mention sous chaque classe).');
        return;
      }
      if (!chosen.length) { showError('Cliquez d’abord sur la classe (ou les classes) qui doit recevoir le quiz.'); return; }
      var count = chosen.reduce(function (sum, c) { return sum + Number(c.dataset.students || 0); }, 0);
      var names = chosen.map(function (c) { return c.dataset.name; });
      var where = names.length > 1
        ? 'aux classes ' + names.slice(0, -1).join(', ') + ' et ' + names[names.length - 1]
        : 'à la classe ' + names[0];
      var deadline = form.elements.deadline ? form.elements.deadline.value : '';
      var message = 'Affecter « ' + title.trim() + ' » ' + where + ' ? '
        + count + ' élève' + (count > 1 ? 's' : '') + ' le recevr' + (count > 1 ? 'ont' : 'a')
        + (deadline ? ', à rendre avant le ' + new Date(deadline).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : '') + '.';
      if (!dialog || !dialog.showModal) {
        if (window.confirm(message)) submitNow();
        return;
      }
      text.textContent = message;
      dialog.showModal();
      if (confirmButton) confirmButton.focus();
    });
    var cancel = document.getElementById('assignCancel');
    if (cancel && dialog) cancel.addEventListener('click', function () { dialog.close(); });
    if (confirmButton) confirmButton.addEventListener('click', submitNow);
  });
})();

/** Formulaire d'import : seules les classes du niveau choisi sont proposées. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var level = document.getElementById('quizLevel');
    var target = document.getElementById('quizTargetClass');
    var help = document.getElementById('quizTargetHelp');
    if (!level || !target) return;
    var defaultHelp = help ? help.textContent : '';
    function filter() {
      var visible = 0;
      Array.prototype.forEach.call(target.options, function (option) {
        if (!option.value) return;
        var ok = !level.value || option.dataset.niveau === level.value;
        option.hidden = !ok;
        option.disabled = !ok;
        if (ok) visible += 1;
        if (!ok && option.selected) target.value = '';
      });
      // Une seule classe à ce niveau : elle est choisie d'office.
      if (level.value && visible === 1 && !target.value) {
        var only = Array.prototype.find.call(target.options, function (o) { return o.value && !o.disabled; });
        if (only) target.value = only.value;
      }
      if (help) {
        help.textContent = level.value && !visible
          ? 'Aucune de vos classes n’est à ce niveau : vous pourrez choisir la classe plus tard.'
          : defaultHelp;
        help.classList.toggle('text-danger', !!(level.value && !visible));
      }
    }
    level.addEventListener('change', filter);
    filter();
  });
})();

/** Import en une page : classe → niveau automatique, cours unique choisi d'office, confirmation d'envoi. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('quizImportForm');
    if (!form) return;
    var target = document.getElementById('quizTargetClass');
    var level = document.getElementById('quizLevel');
    var course = document.getElementById('quizCourse');
    var courseField = document.getElementById('quizCourseField');
    var lesson = document.getElementById('quizLesson');
    var file = document.getElementById('quizJsonFile');
    var fileName = document.getElementById('quizFileName');
    var dialog = document.getElementById('importConfirm');
    var sendBtn = document.getElementById('importSendBtn');
    var confirmed = false;

    function visibleOptions(select) {
      return Array.prototype.filter.call(select.options, function (o) { return o.value && !o.disabled && !o.hidden; });
    }
    // Un seul cours pour ce niveau : il est choisi et le champ s'efface.
    function autoCourse() {
      var options = visibleOptions(course);
      if (options.length === 1 && course.value !== options[0].value) {
        course.value = options[0].value;
        course.dispatchEvent(new Event('change'));
      }
      if (courseField) courseField.classList.toggle('is-auto', options.length === 1);
    }
    var extras = document.getElementById('quizExtraClasses');
    function updateExtras() {
      if (!extras || !target) return;
      var option = target.options[target.selectedIndex];
      var niveau = option && option.value ? option.dataset.niveau : '';
      var shown = 0;
      Array.prototype.forEach.call(extras.querySelectorAll('.qi-extra-class'), function (item) {
        var ok = !!niveau && item.dataset.niveau === niveau && item.dataset.id !== target.value;
        item.hidden = !ok;
        var box = item.querySelector('input');
        box.disabled = !ok;
        if (!ok) box.checked = false;
        if (ok) shown += 1;
      });
      extras.hidden = !shown;
    }
    function extraChosen() {
      return extras ? Array.prototype.slice.call(extras.querySelectorAll('input:checked:not(:disabled)')) : [];
    }
    if (target) target.addEventListener('change', updateExtras);
    updateExtras();
    if (target && level) {
      target.addEventListener('change', function () {
        var option = target.options[target.selectedIndex];
        if (option && option.dataset.niveau && level.value !== option.dataset.niveau) {
          level.value = option.dataset.niveau;
          level.dispatchEvent(new Event('change'));
        }
        autoCourse();
      });
    }
    if (level) level.addEventListener('change', function () { setTimeout(autoCourse, 0); });
    setTimeout(autoCourse, 0);

    var errorBox = document.getElementById('quizImportError');
    var drop = fileName ? fileName.parentElement : null;
    var labels = { quizTargetClass: 'la classe', quizLevel: 'le niveau', quizCourse: 'le cours',
      quizLesson: 'la leçon', secondsPerQuestion: 'le temps par question', quizJsonFile: 'le fichier JSON du quiz' };

    function showFile() {
      var has = !!(file.files && file.files[0]);
      if (fileName) fileName.textContent = has ? '✓ ' + file.files[0].name : 'Choisir ou déposer le fichier .json';
      if (drop) { drop.classList.toggle('has-file', has); drop.classList.remove('is-invalid'); }
      if (has && errorBox) errorBox.hidden = true;
    }
    if (file) file.addEventListener('change', showFile);
    // Glisser-déposer le fichier sur la zone (une étiquette seule ne le reçoit pas).
    if (drop && file) {
      ['dragenter', 'dragover'].forEach(function (name) {
        drop.addEventListener(name, function (event) { event.preventDefault(); drop.classList.add('is-dragover'); });
      });
      drop.addEventListener('dragleave', function () { drop.classList.remove('is-dragover'); });
      drop.addEventListener('drop', function (event) {
        event.preventDefault();
        drop.classList.remove('is-dragover');
        if (event.dataTransfer && event.dataTransfer.files.length) {
          try { file.files = event.dataTransfer.files; } catch (e) { return; }
          showFile();
        }
      });
    }

    // Message visible au lieu d'un clic « sans effet » quand un champ manque.
    function check(needClass) {
      var missing = [];
      var first = null;
      if (needClass && target && !target.value) { missing.push(labels.quizTargetClass); first = target; }
      Array.prototype.forEach.call(form.querySelectorAll('select[required], input[required]'), function (field) {
        if (field.checkValidity()) return;
        missing.push(labels[field.id] || field.name);
        first = first || field;
      });
      if (drop) drop.classList.toggle('is-invalid', !!(file && !file.checkValidity()));
      if (!missing.length) { if (errorBox) errorBox.hidden = true; return true; }
      if (errorBox) {
        errorBox.textContent = 'Il manque : ' + missing.join(', ') + '.';
        errorBox.hidden = false;
      }
      var focusTarget = first === file && drop ? drop : first;
      if (focusTarget && focusTarget.scrollIntoView) focusTarget.scrollIntoView({ block: 'center', behavior: 'smooth' });
      if (first && first !== file) first.focus({ preventScroll: true });
      return false;
    }

    function sendNow() {
      // Envoi direct, sans requestSubmit (absent des anciens Safari) : on ajoute send_now=1.
      confirmed = true;
      var flag = document.createElement('input');
      flag.type = 'hidden';
      flag.name = 'send_now';
      flag.value = '1';
      form.appendChild(flag);
      if (sendBtn) { sendBtn.disabled = true; sendBtn.textContent = 'Envoi…'; }
      HTMLFormElement.prototype.submit.call(form);
    }

    form.setAttribute('novalidate', '');
    var clicked = null;
    Array.prototype.forEach.call(form.querySelectorAll('button[type="submit"]'), function (button) {
      button.addEventListener('click', function () { clicked = button; });
    });
    form.addEventListener('submit', function (event) {
      if (confirmed) return;
      var submitter = event.submitter || clicked;
      clicked = null;
      var sending = !submitter || submitter.id !== 'importDraftBtn';
      if (!check(sending)) { event.preventDefault(); return; }
      if (!sending) return;  // brouillon : envoi normal du formulaire
      event.preventDefault();
      if (!dialog || !dialog.showModal) {
        if (window.confirm('Importer le quiz et l’envoyer à la classe choisie ?')) sendNow();
        return;
      }
      var option = target.options[target.selectedIndex];
      var students = Number(option.dataset.students || 0);
      var names = [option.textContent.split('·')[0].trim()];
      extraChosen().forEach(function (box) {
        names.push(box.dataset.name);
        students += Number(box.dataset.students || 0);
      });
      var where = names.length > 1
        ? 'aux classes ' + names.slice(0, -1).join(', ') + ' et ' + names[names.length - 1]
        : 'à la classe ' + names[0];
      var lessonName = lesson.options[lesson.selectedIndex].textContent.trim();
      var deadline = form.elements.deadline.value;
      document.getElementById('importConfirmText').textContent =
        'Le quiz du fichier « ' + file.files[0].name + ' » (leçon : ' + lessonName + ') sera envoyé '
        + where + ' : ' + students + ' élève' + (students > 1 ? 's' : '')
        + (deadline ? ', à rendre avant le ' + new Date(deadline).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : '') + '.';
      dialog.showModal();
    });
    if (dialog) {
      document.getElementById('importCancel').addEventListener('click', function () { dialog.close(); });
      document.getElementById('importConfirmBtn').addEventListener('click', function () {
        this.disabled = true;
        this.textContent = 'Envoi…';
        sendNow();
      });
    }
  });
})();

/** Prompt pour une IA : plan et règles du cours de la leçon choisie, prêt à copier. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var bloc = document.getElementById('quizPrompt');
    if (!bloc) return;
    var lesson = document.getElementById('quizLesson');
    var bouton = document.getElementById('promptGenerer');
    var resultat = document.getElementById('promptResultat');
    var texte = document.getElementById('promptTexte');
    var copier = document.getElementById('promptCopier');
    var erreur = document.getElementById('promptErreur');
    function dire(message) { erreur.textContent = message || ''; erreur.hidden = !message; }
    bouton.addEventListener('click', function () {
      dire('');
      if (!lesson || !lesson.value) { dire('Choisissez d’abord la leçon (étape 2).'); return; }
      var params = new URLSearchParams({
        lesson: lesson.value,
        n: document.getElementById('promptNombre').value || '10',
        difficulte: document.getElementById('promptDifficulte').value
      });
      bouton.disabled = true;
      fetch(bloc.getAttribute('data-url') + '?' + params.toString(), {
        credentials: 'same-origin', headers: { 'Accept': 'application/json' }
      }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) { dire(res.d.error || 'Prompt indisponible.'); return; }
          texte.value = res.d.prompt;
          resultat.hidden = false;
          copier.innerHTML = '<i class="bi bi-clipboard" aria-hidden="true"></i> Copier le prompt';
        })
        .catch(function () { dire('Prompt indisponible (connexion ?).'); })
        .then(function () { bouton.disabled = false; });
    });
    copier.addEventListener('click', function () {
      var fait = function () { copier.innerHTML = '<i class="bi bi-clipboard-check" aria-hidden="true"></i> Copié'; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texte.value).then(fait, function () { texte.select(); document.execCommand('copy'); fait(); });
      } else {
        texte.select();
        document.execCommand('copy');
        fait();
      }
    });
  });
})();
