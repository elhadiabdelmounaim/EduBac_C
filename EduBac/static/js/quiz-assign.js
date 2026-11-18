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
