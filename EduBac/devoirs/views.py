"""Pages des devoirs : liste (professeur ou élève), création et modification, fichiers
(ajout, verrou, suppression) et téléchargement contrôlé."""
import mimetypes
from itertools import groupby

from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import login_required_simple, teacher_required

from . import acces
from .models import Devoir, FichierDevoir
from .services import (EN_LIGNE, ErreurDevoir, ajouter_fichiers, lire_date, notifier_nouveau_devoir,
                       supprimer_fichier, verifier_fichiers)


def _classes_par_niveau(classes, cochees=()):
    """[(libellé du niveau, [classe…])] avec « cochee » sur chaque classe."""
    cochees = {int(c) for c in cochees}
    groupes = []
    for _, groupe in groupby(classes, key=lambda c: c.niveau):
        groupe = list(groupe)
        for c in groupe:
            c.cochee = c.pk in cochees
        groupes.append((groupe[0].get_niveau_display(), groupe))
    return groupes


def _devoir_gere(request, pk):
    devoir = get_object_or_404(Devoir, pk=pk)
    if not acces.peut_gerer(request.edubac_user, devoir):
        raise Http404
    return devoir


@login_required_simple
def index(request):
    user = request.edubac_user
    maintenant = timezone.now()
    if user.is_teacher():
        devoirs = acces.devoirs_geres(user)
        gestion = True
    else:
        devoirs = acces.devoirs_de_l_eleve(user)
        gestion = False
    devoirs = list(devoirs.prefetch_related('classes', 'fichiers'))
    for d in devoirs:
        d.liste_fichiers = list(d.fichiers.all())
        for f in d.liste_fichiers:
            f.visible = f.est_visible(maintenant)
        d.depasse = bool(d.date_limite and d.date_limite < maintenant)
    return render(request, 'devoirs/index.html', {
        'devoirs': devoirs, 'gestion': gestion, 'page_title': 'Devoirs',
    })


@teacher_required
def creer(request):
    user = request.edubac_user
    classes = list(acces.classes_gerees(user))
    valeurs = {'titre': '', 'consigne': '', 'date_limite': '', 'ouverture_le': ''}
    cochees = []
    if request.method == 'POST':
        valeurs = {k: request.POST.get(k, '').strip() for k in valeurs}
        cochees = [c for c in request.POST.getlist('classes') if c.isdecimal()]
        visibles = request.FILES.getlist('fichiers')
        verrouilles = request.FILES.getlist('fichiers_verrouilles')
        try:
            if not valeurs['titre']:
                raise ErreurDevoir('Donnez un titre au devoir.')
            choisies = [c for c in classes if str(c.pk) in cochees]
            if not choisies:
                raise ErreurDevoir('Choisissez au moins une classe.')
            date_limite = lire_date(valeurs['date_limite'], 'La date limite')
            ouverture_le = lire_date(valeurs['ouverture_le'], 'La date d’ouverture')
            verifier_fichiers(visibles + verrouilles)
            with transaction.atomic():
                devoir = Devoir.objects.create(
                    teacher=user, titre=valeurs['titre'][:200], consigne=valeurs['consigne'],
                    date_limite=date_limite,
                )
                devoir.classes.set(choisies)
                ajouter_fichiers(devoir, visibles)
                ajouter_fichiers(devoir, verrouilles, verrouille=True, ouverture_le=ouverture_le)
                eleves = list(acces.eleves_des_classes(choisies))
                transaction.on_commit(lambda: notifier_nouveau_devoir(devoir, eleves))
        except ErreurDevoir as exc:
            messages.error(request, str(exc))
        else:
            noms = ', '.join(c.name for c in choisies)
            messages.success(request, f'Devoir « {devoir.titre} » publié pour {noms} '
                                      f'({len(eleves)} élève{"s" if len(eleves) > 1 else ""} prévenu{"s" if len(eleves) > 1 else ""}).')
            return redirect('devoirs:detail', devoir.pk)
    return render(request, 'devoirs/form.html', {
        'valeurs': valeurs, 'groupes': _classes_par_niveau(classes, cochees), 'creation': True,
        'page_title': 'Nouveau devoir',
    })


@teacher_required
def modifier(request, pk):
    devoir = _devoir_gere(request, pk)
    user = request.edubac_user
    classes = list(acces.classes_gerees(user))
    # Une classe déjà choisie reste proposée même si elle n'est plus active ou appartient à un autre.
    deja = list(devoir.classes.all())
    for c in deja:
        if c not in classes:
            classes.append(c)
    classes.sort(key=lambda c: (c.niveau, c.name))
    valeurs = {
        'titre': devoir.titre, 'consigne': devoir.consigne,
        'date_limite': timezone.localtime(devoir.date_limite).strftime('%Y-%m-%dT%H:%M') if devoir.date_limite else '',
    }
    cochees = [c.pk for c in deja]
    if request.method == 'POST':
        valeurs = {k: request.POST.get(k, '').strip() for k in valeurs}
        cochees = [c for c in request.POST.getlist('classes') if c.isdecimal()]
        try:
            if not valeurs['titre']:
                raise ErreurDevoir('Donnez un titre au devoir.')
            choisies = [c for c in classes if str(c.pk) in cochees]
            if not choisies:
                raise ErreurDevoir('Choisissez au moins une classe.')
            date_limite = lire_date(valeurs['date_limite'], 'La date limite')
            with transaction.atomic():
                devoir.titre = valeurs['titre'][:200]
                devoir.consigne = valeurs['consigne']
                devoir.date_limite = date_limite
                devoir.save()
                nouvelles = [c for c in choisies if c not in deja]
                devoir.classes.set(choisies)
                # Seuls les élèves des classes ajoutées découvrent le devoir.
                anciens = set(acces.eleves_des_classes(deja).values_list('pk', flat=True))
                eleves = [e for e in acces.eleves_des_classes(nouvelles) if e.pk not in anciens] if nouvelles else []
                transaction.on_commit(lambda: notifier_nouveau_devoir(devoir, eleves))
        except ErreurDevoir as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'Devoir mis à jour.' + (
                f' {len(eleves)} élève{"s" if len(eleves) > 1 else ""} des classes ajoutées prévenu{"s" if len(eleves) > 1 else ""}.'
                if eleves else ''))
            return redirect('devoirs:detail', devoir.pk)
    return render(request, 'devoirs/form.html', {
        'valeurs': valeurs, 'groupes': _classes_par_niveau(classes, cochees), 'creation': False,
        'devoir': devoir, 'page_title': f'Modifier « {devoir.titre} »',
    })


@login_required_simple
def detail(request, pk):
    devoir = get_object_or_404(Devoir.objects.prefetch_related('classes'), pk=pk)
    user = request.edubac_user
    if not acces.peut_voir(user, devoir):
        messages.error(request, 'Ce devoir n’est pas destiné à votre classe.')
        return redirect('devoirs:index')
    gestion = acces.peut_gerer(user, devoir)
    maintenant = timezone.now()
    fichiers = list(devoir.fichiers.all())
    for f in fichiers:
        f.visible = f.est_visible(maintenant)
    return render(request, 'devoirs/detail.html', {
        'devoir': devoir, 'fichiers': fichiers, 'gestion': gestion,
        'depasse': bool(devoir.date_limite and devoir.date_limite < maintenant),
        'page_title': devoir.titre,
    })


@require_POST
@teacher_required
def supprimer(request, pk):
    devoir = _devoir_gere(request, pk)
    titre = devoir.titre
    with transaction.atomic():
        for f in list(devoir.fichiers.all()):
            supprimer_fichier(f)
        devoir.delete()
    messages.success(request, f'Devoir « {titre} » supprimé.')
    return redirect('devoirs:index')


@require_POST
@teacher_required
def ajouter(request, pk):
    devoir = _devoir_gere(request, pk)
    fichiers = request.FILES.getlist('fichiers')
    verrouille = request.POST.get('verrouille') == '1'
    try:
        if not fichiers:
            raise ErreurDevoir('Choisissez au moins un fichier.')
        ouverture_le = lire_date(request.POST.get('ouverture_le'), 'La date d’ouverture') if verrouille else None
        verifier_fichiers(fichiers)
        with transaction.atomic():
            ajouter_fichiers(devoir, fichiers, verrouille=verrouille, ouverture_le=ouverture_le)
    except ErreurDevoir as exc:
        messages.error(request, str(exc))
    else:
        n = len(fichiers)
        messages.success(request, f'{n} fichier{"s" if n > 1 else ""} ajouté{"s" if n > 1 else ""}'
                                  + (' (verrouillé' + ('s' if n > 1 else '') + ').' if verrouille else '.'))
    return redirect('devoirs:detail', devoir.pk)


def _fichier_gere(request, pk):
    fichier = get_object_or_404(FichierDevoir.objects.select_related('devoir'), pk=pk)
    if not acces.peut_gerer(request.edubac_user, fichier.devoir):
        raise Http404
    return fichier


@require_POST
@teacher_required
def verrou(request, pk):
    fichier = _fichier_gere(request, pk)
    action = request.POST.get('action')
    try:
        if action == 'deverrouiller':
            fichier.verrouille, fichier.ouverture_le = False, None
            texte = f'« {fichier.nom} » est maintenant visible par les élèves.'
        elif action == 'verrouiller':
            fichier.verrouille = True
            fichier.ouverture_le = lire_date(request.POST.get('ouverture_le'), 'La date d’ouverture')
            texte = f'« {fichier.nom} » est verrouillé' + (
                f' jusqu’au {timezone.localtime(fichier.ouverture_le):%d/%m/%Y à %H:%M}.' if fichier.ouverture_le
                else ' : les élèves ne peuvent pas l’ouvrir.')
        else:
            raise ErreurDevoir('Action inconnue.')
    except ErreurDevoir as exc:
        messages.error(request, str(exc))
    else:
        fichier.save(update_fields=['verrouille', 'ouverture_le'])
        messages.success(request, texte)
    return redirect('devoirs:detail', fichier.devoir_id)


@require_POST
@teacher_required
def retirer(request, pk):
    fichier = _fichier_gere(request, pk)
    devoir_id, nom = fichier.devoir_id, fichier.nom
    with transaction.atomic():
        supprimer_fichier(fichier)
    messages.success(request, f'« {nom} » supprimé.')
    return redirect('devoirs:detail', devoir_id)


@login_required_simple
def telecharger(request, pk):
    """Seule porte vers un fichier : devoir de la classe de l'élève et fichier visible."""
    fichier = get_object_or_404(FichierDevoir.objects.select_related('devoir'), pk=pk)
    user = request.edubac_user
    if not acces.peut_voir(user, fichier.devoir):
        raise Http404
    if not acces.peut_gerer(user, fichier.devoir) and not fichier.est_visible():
        messages.info(request, f'« {fichier.nom} » n’est pas encore disponible.')
        return redirect('devoirs:detail', fichier.devoir_id)
    try:
        flux = fichier.fichier.open('rb')
    except (FileNotFoundError, OSError, ValueError):
        raise Http404 from None
    type_en_ligne = EN_LIGNE.get(fichier.extension)
    telecharge = not type_en_ligne or request.GET.get('telecharger') == '1'
    reponse = FileResponse(
        flux, as_attachment=telecharge, filename=fichier.nom,
        content_type=type_en_ligne or mimetypes.guess_type(fichier.nom)[0] or 'application/octet-stream',
    )
    reponse['Cache-Control'] = 'private, no-store'
    reponse['X-Content-Type-Options'] = 'nosniff'
    return reponse
