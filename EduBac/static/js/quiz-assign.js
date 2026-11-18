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

    if (file && fileName) {
      file.addEventListener('change', function () {
        fileName.textContent = file.files && file.files[0] ? '✓ ' + file.files[0].name : 'Choisir ou déposer le fichier .json';
        fileName.parentElement.classList.toggle('has-file', !!(file.files && file.files[0]));
      });
    }

    form.addEventListener('submit', function (event) {
      var submitter = event.submitter;
      if (!submitter || submitter.value !== '1' || confirmed) return;
      event.preventDefault();
      if (!target.value) {
        target.setCustomValidity('Choisissez la classe qui recevra le quiz.');
        target.reportValidity();
        target.addEventListener('change', function () { target.setCustomValidity(''); }, { once: true });
        return;
      }
      if (!form.reportValidity()) return;
      if (!dialog || !dialog.showModal) { confirmed = true; form.requestSubmit(sendBtn); return; }
      var option = target.options[target.selectedIndex];
      var students = Number(option.dataset.students || 0);
      var lessonName = lesson.options[lesson.selectedIndex].textContent.trim();
      var deadline = form.elements.deadline.value;
      document.getElementById('importConfirmText').textContent =
        'Le quiz du fichier « ' + file.files[0].name + ' » (leçon : ' + lessonName + ') sera envoyé à la classe '
        + option.textContent.split('·')[0].trim() + ' : ' + students + ' élève' + (students > 1 ? 's' : '')
        + (deadline ? ', à rendre avant le ' + new Date(deadline).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }) : '') + '.';
      dialog.showModal();
    });
    if (dialog) {
      document.getElementById('importCancel').addEventListener('click', function () { dialog.close(); });
      document.getElementById('importConfirmBtn').addEventListener('click', function () {
        confirmed = true;
        this.disabled = true;
        this.textContent = 'Envoi…';
        form.requestSubmit(sendBtn);
      });
    }
  });
})();
