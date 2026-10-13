(function() {
    var niveauSelect = document.getElementById('niveauSelect');
    var lessonSelect = document.getElementById('lessonSelect');
    if (!niveauSelect || !lessonSelect) return;
    var sourceSelect = document.getElementById('sourceFileSelect');
    var sourceHint = document.getElementById('sourceFileHint');
    var generationMode = document.getElementById('generationMode');
    var topicCard = document.getElementById('topicCard');
    var subjectInput = document.getElementById('quizSubject');
    var uploadInput = document.getElementById('quizResourceUploads');
    var selectionSummary = document.getElementById('resourceSelectionSummary');
    var uploadSummary = document.getElementById('uploadFileSummary');
    var validationMessage = document.getElementById('resourceValidationMessage');
    var selectAllButton = document.getElementById('selectAllResources');
    var clearButton = document.getElementById('clearResources');
    var resourcesByLesson = JSON.parse(document.getElementById('resource-options-data').textContent || '{}');
    var initiallySelected = JSON.parse(document.getElementById('selected-source-files-data').textContent || '[]');
    if (!Array.isArray(initiallySelected)) initiallySelected = [];
    var initialSelectionPending = true;
    var maxFiles = 5;
    var maxFileBytes = 10 * 1024 * 1024;
    var maxTotalBytes = 25 * 1024 * 1024;
    var maxCombinedFiles = 12;

    function selectedValues() {
        return Array.prototype.filter.call(sourceSelect.options, function(option) {
            return option.selected;
        }).map(function(option) { return option.value; });
    }

    function activeUploadFiles() {
        return uploadInput.disabled
            ? []
            : Array.prototype.slice.call(uploadInput.files || []);
    }

    function updateResourceSummary() {
        var selectedCount = selectedValues().length;
        if (selectionSummary) {
            selectionSummary.textContent = generationMode.value === 'topic'
                ? 'Les ressources sélectionnées ne seront pas envoyées en mode sujet.'
                : selectedCount
                    ? selectedCount + (selectedCount === 1 ? ' ressource sélectionnée.' : ' ressources sélectionnées.')
                    : 'Aucune ressource sélectionnée.';
        }
        if (selectAllButton) selectAllButton.disabled = sourceSelect.disabled || !sourceSelect.options.length;
        if (clearButton) clearButton.disabled = sourceSelect.disabled || selectedCount === 0;
    }

    function updateSources(selected) {
        var topicMode = generationMode.value === 'topic';
        topicCard.hidden = !topicMode;
        if (subjectInput) subjectInput.disabled = !topicMode;
        sourceSelect.disabled = topicMode || !lessonSelect.value;
        uploadInput.disabled = topicMode;
        if (topicMode) {
            sourceHint.textContent = 'Mode sujet : la sélection de ressources et les fichiers ajoutés sont désactivés et ne seront pas envoyés.';
            updateResourceSummary();
            updateUploadSummary();
            return;
        }

        var resources = resourcesByLesson[lessonSelect.value] || [];
        var keep = Array.isArray(selected) ? selected : [];
        sourceSelect.innerHTML = '';
        resources.forEach(function(resource) {
            var option = new Option(resource.label, resource.value);
            option.selected = keep.indexOf(resource.value) !== -1;
            sourceSelect.add(option);
        });
        sourceSelect.disabled = !lessonSelect.value || resources.length === 0;
        sourceHint.textContent = !lessonSelect.value
            ? 'Choisissez une leçon pour afficher ses ressources. Sélection multiple : Ctrl (Windows) ou Cmd (Mac), puis clic.'
            : resources.length
                ? 'Sélectionnez une ou plusieurs ressources. Ctrl (Windows) ou Cmd (Mac), puis clic, permet une sélection multiple.'
                : 'Aucune ressource disponible pour cette leçon. Vous pouvez ajouter des fichiers ou décrire le quiz sans ressource.';
        updateResourceSummary();
        updateUploadSummary();
    }

    function updateUploadSummary() {
        var files = activeUploadFiles();
        if (uploadInput.disabled) {
            uploadSummary.textContent = 'Fichiers désactivés en mode sujet ; ils ne seront pas envoyés.';
        } else {
            uploadSummary.textContent = files.length
                ? files.length + (files.length === 1 ? ' fichier choisi : ' : ' fichiers choisis : ') +
                    files.map(function(file) { return file.name; }).join(', ')
                : 'Aucun nouveau fichier choisi.';
        }
        validateResources(false);
    }

    function validateResources(showMessage) {
        var files = activeUploadFiles();
        var selectedCount = sourceSelect.disabled ? 0 : selectedValues().length;
        var totalBytes = 0;
        var problems = [];
        if (files.length > maxFiles) problems.push('Vous pouvez ajouter au maximum 5 fichiers à la fois.');
        files.forEach(function(file) {
            totalBytes += file.size;
            if (file.size > maxFileBytes) problems.push('« ' + file.name + ' » dépasse la limite de 10 Mio.');
            if (!/\.(txt|md|pdf|docx)$/i.test(file.name)) problems.push('Format non pris en charge pour « ' + file.name + ' ».');
        });
        if (totalBytes > maxTotalBytes) problems.push('La taille totale des fichiers ajoutés dépasse 25 Mio.');
        if (selectedCount + files.length > maxCombinedFiles) problems.push('La sélection combinée ne peut pas dépasser 12 ressources.');
        if (validationMessage) {
            validationMessage.hidden = !problems.length;
            validationMessage.textContent = problems.join(' ');
        }
        if (showMessage && problems.length) uploadInput.focus();
        return problems.length === 0;
    }

    var generationForm = document.getElementById('genForm');
    if (generationForm) {
        generationForm.addEventListener('submit', function(event) {
            if (event.submitter && event.submitter.value !== 'generate') return;
            var isTopic = generationMode.value === 'topic';
            var chosenResources = isTopic ? 0 : selectedValues().length + activeUploadFiles().length;
            var description = document.getElementById('quizDescription');
            var subject = document.getElementById('quizSubject');
            var hasInstructions = !!(description && description.value.trim()) ||
                (isTopic && subject && !!subject.value.trim());
            var validFiles = isTopic || validateResources(true);
            if (!validFiles || (!chosenResources && !hasInstructions)) {
                event.preventDefault();
                event.stopImmediatePropagation();
                if (!validFiles) return;
                validationMessage.hidden = false;
                validationMessage.textContent = isTopic
                    ? 'Indiquez un sujet ou des consignes avant de générer sans ressource.'
                    : 'Ajoutez une description ou un sujet explicite avant de générer sans ressource.';
                if (description && !description.value.trim()) {
                    if (isTopic && subject && !subject.value.trim()) subject.focus();
                    else description.focus();
                }
            }
        }, true);
    }

    sourceSelect.addEventListener('change', function() {
        updateResourceSummary();
        validateResources(false);
    });
    uploadInput.addEventListener('change', updateUploadSummary);
    selectAllButton.addEventListener('click', function() {
        Array.prototype.forEach.call(sourceSelect.options, function(option) { option.selected = true; });
        updateResourceSummary();
        validateResources(false);
    });
    clearButton.addEventListener('click', function() {
        Array.prototype.forEach.call(sourceSelect.options, function(option) { option.selected = false; });
        updateResourceSummary();
        validateResources(false);
    });
    lessonSelect.addEventListener('change', function() {
        initialSelectionPending = false;
        updateSources([]);
    });
    generationMode.addEventListener('change', function() {
        updateSources(selectedValues());
    });

    var placeholder = lessonSelect.options[0];
    var optionNodes = lessonSelect.getElementsByTagName('option');
    var lessonOptions = [];
    for (var i = 0; i < optionNodes.length; i++) {
        if (optionNodes[i].getAttribute('data-niveau') !== null) {
            lessonOptions.push(optionNodes[i]);
        }
    }

    function updateLessons(resetSelection) {
        var niveau = niveauSelect.value;
        var previousLesson = resetSelection ? '' : lessonSelect.value;
        var matchingLessons = [];
        for (var i = 0; i < lessonOptions.length; i++) {
            if (lessonOptions[i].getAttribute('data-niveau') === niveau) {
                matchingLessons.push(lessonOptions[i]);
            }
        }

        while (lessonSelect.firstChild) {
            lessonSelect.removeChild(lessonSelect.firstChild);
        }
        lessonSelect.appendChild(placeholder);
        for (var i = 0; i < matchingLessons.length; i++) {
            var option = matchingLessons[i];
            option.removeAttribute('hidden');
            option.removeAttribute('disabled');
            lessonSelect.appendChild(option);
        }

        placeholder.textContent = niveau
            ? (matchingLessons.length ? '— Choisir une leçon —' : '— Aucune leçon disponible —')
            : '— Choisir d’abord un niveau —';
        lessonSelect.disabled = !niveau || matchingLessons.length === 0;

        var previousLessonAvailable = false;
        for (var i = 0; i < matchingLessons.length; i++) {
            if (matchingLessons[i].value === previousLesson) {
                previousLessonAvailable = true;
                break;
            }
        }
        if (previousLesson && previousLessonAvailable) {
            lessonSelect.value = previousLesson;
        } else {
            lessonSelect.value = '';
        }
    }

    var handleNiveauChange = function() {
        updateLessons(true);
        initialSelectionPending = false;
        updateSources([]);
    };
    if (niveauSelect.addEventListener) {
        niveauSelect.addEventListener('change', handleNiveauChange);
    } else if (niveauSelect.attachEvent) {
        niveauSelect.attachEvent('onchange', handleNiveauChange);
    } else {
        niveauSelect.onchange = handleNiveauChange;
    }
    updateLessons(false);
    updateSources(initialSelectionPending && lessonSelect.value ? initiallySelected : []);
    initialSelectionPending = false;
    updateUploadSummary();
})();
