/** Affectation d'un quiz importé : choix de la classe puis confirmation. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('sendQuizForm');
    var dialog = document.getElementById('assignConfirm');
    if (!form || !dialog || !dialog.showModal) return;
    var confirmed = false;
    var text = document.getElementById('assignConfirmText');
    var title = (document.getElementById('quiz-preview-title') || {}).textContent || 'ce quiz';

    form.addEventListener('submit', function (event) {
      if (confirmed) return;
      event.preventDefault();
      var choice = form.querySelector('input[name="classroom"]:checked');
      if (!choice) { form.reportValidity(); return; }
      var count = Number(choice.dataset.students || 0);
      var deadline = form.elements.deadline.value;
      text.textContent = 'Affecter « ' + title.trim() + ' » à la classe ' + choice.dataset.name + ' ? '
        + count + ' élève' + (count > 1 ? 's' : '') + ' le recevr' + (count > 1 ? 'ont' : 'a')
        + (deadline ? ', à rendre avant le ' + new Date(deadline).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : '') + '.';
      dialog.showModal();
      document.getElementById('assignConfirmBtn').focus();
    });
    document.getElementById('assignCancel').addEventListener('click', function () { dialog.close(); });
    document.getElementById('assignConfirmBtn').addEventListener('click', function () {
      confirmed = true;
      var button = document.getElementById('assignConfirmBtn');
      button.disabled = true;
      button.textContent = 'Affectation…';
      form.submit();
    });
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
