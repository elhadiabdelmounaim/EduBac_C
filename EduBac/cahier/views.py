"""Cahier de textes : enregistrement depuis le cours (panneau « Séance ») et consultation."""
import datetime
import json
import re

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import teacher_required
from classrooms.models import Classroom
from education.models import Course, Lesson

from education.repartition import duree_prevue_minutes, repartition_de_lecon

from .models import Seance, SeanceElement
from .pdf import document
from .rubriques import elements, plan_de_lecon
from .suivi import bilan, bilan_lecon, duree, lire_duree, minutes_realisees


def _enseignant(request):
    user = getattr(request, 'edubac_user', None)
    return user if user and user.is_teacher() else None


def _refus(message, status):
    return JsonResponse({'ok': False, 'message': message}, status=status)


def _classes(user):
    return Classroom.objects.filter(teacher=user, is_active=True).order_by('name')


def _lire_date(texte):
    try:
        return datetime.date.fromisoformat(str(texte or ''))
    except ValueError:
        return None


@require_GET
def etat(request, pk):
    """Plan du cours, classes de l'enseignant et, pour une classe et une date, ce qui est
    déjà enregistré (pour pré-cocher) et ce qui a été traité lors des autres séances."""
    user = _enseignant(request)
    if user is None:
        return _refus('Réservé aux enseignants.', 403)
    lesson = get_object_or_404(Lesson.objects.select_related('course'), pk=pk)
    plan = plan_de_lecon(lesson)
    if plan is None:
        raise Http404
    classes = list(_classes(user))
    data = {
        'ok': True,
        'plan': plan,
        'classes': [{'id': c.pk, 'nom': c.name, 'niveau': c.get_niveau_display(),
                     'meme_niveau': c.niveau == lesson.course.niveau} for c in classes],
        'selection': [], 'deja': {}, 'existe': False,
        'repartition': repartition_de_lecon(lesson),
        'cahier_url': reverse('cahier:niveau', args=[lesson.course.niveau]),
        'observations': '',
        'duree': None,
        'suivi': None,
        'prevu_texte': duree(duree_prevue_minutes(lesson)) if duree_prevue_minutes(lesson) else '',
        'creer_classe_url': reverse('classrooms:create'),
    }
    classe = next((c for c in classes if str(c.pk) == request.GET.get('classe')), None)
    jour = _lire_date(request.GET.get('date'))
    if classe and jour:
        seances = (Seance.objects.filter(teacher=user, classroom=classe, lesson=lesson)
                   .prefetch_related('elements').order_by('date'))
        for s in seances:
            cles = [e.key for e in s.elements.all()]
            if s.date == jour:
                data['selection'] = cles
                data['existe'] = True
                data['observations'] = s.observations
                data['duree'] = minutes_realisees(s)
            else:
                for k in cles:
                    data['deja'][k] = s.date.strftime('%d/%m')
        data['suivi'] = bilan_lecon(seances, lesson)
    return JsonResponse(data)


@require_POST
def enregistrer(request, pk):
    """Enregistre (ou remplace) la séance du jour choisi pour cette classe et cette leçon."""
    user = _enseignant(request)
    if user is None:
        return _refus('Réservé aux enseignants.', 403)
    lesson = get_object_or_404(Lesson.objects.select_related('course'), pk=pk)
    plan = plan_de_lecon(lesson)
    if plan is None:
        raise Http404
    try:
        corps = json.loads(request.body or b'{}')
    except ValueError:
        return _refus('Requête invalide.', 400)
    classe = _classes(user).filter(pk=str(corps.get('classe') or '0')).first() \
        if str(corps.get('classe') or '').isdigit() else None
    if classe is None:
        return _refus('Choisissez une de vos classes.', 400)
    jour = _lire_date(corps.get('date'))
    if jour is None:
        return _refus('Date invalide.', 400)
    connus = {e['key']: e for e in elements(plan)}
    cles = corps.get('cles') if isinstance(corps.get('cles'), list) else []
    choisis = [connus[k] for k in dict.fromkeys(cles) if isinstance(k, str) and k in connus]
    if len(choisis) != len(set(cles)):
        return _refus('Élément inconnu dans ce cours.', 400)
    if not choisis:
        return _refus('Cochez au moins un élément traité.', 400)
    choisis.sort(key=lambda e: e['ordre'])
    observations = corps.get('observations')
    observations = observations.strip()[:4000] if isinstance(observations, str) else None
    try:
        minutes = lire_duree(corps.get('duree'))
    except ValueError as exc:
        return _refus(str(exc), 400)
    with transaction.atomic():
        seance, cree = Seance.objects.get_or_create(teacher=user, classroom=classe, lesson=lesson, date=jour)
        if not cree:
            seance.elements.all().delete()
        if observations is not None:
            seance.observations = observations
        if minutes is not None:
            seance.duree_minutes = minutes      # remplace la durée précédente : pas de double déduction
        seance.save()
        SeanceElement.objects.bulk_create([
            SeanceElement(seance=seance, key=e['key'], title=e['titre'][:255], partie=e['partie'][:255],
                          sous_titre=e['sous_titre'][:255], order=e['ordre'], minutes=e['minutes'])
            for e in choisis
        ])
    # Plan entièrement traité avec cette classe : la leçon s'ouvre aux élèves.
    from . import acces
    acces.recalculer(classe, lesson)
    return JsonResponse({
        'ok': True, 'cree': cree, 'nombre': len(choisis),
        'message': ('Séance enregistrée' if cree else 'Séance mise à jour')
                   + f' : {len(choisis)} élément{"s" if len(choisis) > 1 else ""}, le {jour:%d/%m/%Y}.',
        'url': reverse('cahier:niveau', args=[lesson.course.niveau]) + f'#seance-{seance.pk}',
        'duree': minutes_realisees(seance),
        'suivi': bilan_lecon(Seance.objects.filter(teacher=user, classroom=classe, lesson=lesson)
                             .prefetch_related('elements'), lesson),
    })


def _regrouper(seance):
    """Éléments d'une séance → [{titre de partie, [{sous-titre, [éléments]}]}]."""
    parties = []
    for e in seance.elements.all():
        if not parties or parties[-1]['titre'] != e.partie:
            parties.append({'titre': e.partie, 'groupes': []})
        groupes = parties[-1]['groupes']
        if not groupes or groupes[-1]['titre'] != e.sous_titre:
            groupes.append({'titre': e.sous_titre, 'elements': []})
        groupes[-1]['elements'].append(e.title)
    return parties


def _progression(seances):
    """Pour chaque séance : temps réellement passé sur la leçon avec cette classe (même
    enseignant) jusqu'à cette séance incluse, comparé à la durée prévue de la leçon."""
    triplets = {(s.teacher_id, s.classroom_id, s.lesson_id) for s in seances}
    if not triplets:
        return
    historiques = {}
    for s in (Seance.objects.filter(teacher_id__in={t for t, _, _ in triplets},
                                    classroom_id__in={c for _, c, _ in triplets},
                                    lesson_id__in={le for _, _, le in triplets})
              .prefetch_related('elements').order_by('date', 'created_at', 'pk')):
        historiques.setdefault((s.teacher_id, s.classroom_id, s.lesson_id), []).append(s)
    for s in seances:
        realise = 0
        for h in historiques.get((s.teacher_id, s.classroom_id, s.lesson_id), []):
            if h.date > s.date:
                break
            realise += minutes_realisees(h)
        s.progression = bilan(duree_prevue_minutes(s.lesson), realise)


def suivi_des_lecons(seances):
    """Une ligne par (enseignant, classe, leçon) : bilan de toutes les séances enregistrées."""
    groupes = {}
    for s in seances:
        groupes.setdefault((s.teacher_id, s.classroom_id, s.lesson_id), []).append(s)
    lignes = []
    for liste in groupes.values():
        s = liste[0]
        lignes.append({'lecon': s.lesson, 'classe': s.classroom, 'enseignant': s.teacher,
                       'seances': len(liste), 'derniere': max(x.date for x in liste),
                       'bilan': bilan_lecon(liste, s.lesson)})
    lignes.sort(key=lambda l: (l['classe'].name, l['lecon'].order, l['lecon'].title, l['enseignant'].pk))
    return lignes

NIVEAUX = dict(Course.NIVEAU_CHOICES)
ICONES = {
    'tronc_commun': 'bi-signpost-split', '1ere_bac_sc': 'bi-flower1', '1ere_bac_sm': 'bi-calculator',
    '1ere_bac_lettres': 'bi-book', '2eme_bac_svt': 'bi-tree', '2eme_bac_pc': 'bi-lightning-charge',
    '2eme_bac_lettres': 'bi-journal-text', '2eme_bac_sm': 'bi-infinity',
}
ACTIVITE = re.compile(r'^(Activit|Application|Exercice)', re.I)


def est_directeur(user):
    return bool(user.is_staff or user.is_superuser)


def seances_visibles(user):
    """Le directeur voit les séances de tous les enseignants ; un enseignant, les siennes."""
    qs = (Seance.objects.select_related('classroom', 'lesson', 'lesson__course', 'teacher')
          .prefetch_related('elements'))
    return qs if est_directeur(user) else qs.filter(teacher=user)


def _niveau_ou_404(niveau):
    if niveau not in NIVEAUX:
        raise Http404
    return NIVEAUX[niveau]


def _numeroter(seances):
    """Numéro de séance : rang chronologique dans le cahier de la classe (même enseignant)."""
    paires = {(s.teacher_id, s.classroom_id) for s in seances}
    if not paires:
        return
    rang, numeros = {}, {}
    lignes = (Seance.objects.filter(teacher_id__in={t for t, _ in paires}, classroom_id__in={c for _, c in paires})
              .order_by('date', 'created_at', 'pk').values_list('pk', 'teacher_id', 'classroom_id'))
    for pk, t, c in lignes:
        if (t, c) in paires:
            rang[(t, c)] = rang.get((t, c), 0) + 1
            numeros[pk] = rang[(t, c)]
    for s in seances:
        s.numero = numeros.get(s.pk)


def preparer(seances):
    """Ajoute à chaque séance ce que l'affichage et le PDF utilisent."""
    _numeroter(seances)
    for s in seances:
        s.parties = _regrouper(s)
        s.minutes_prevues = sum(e.minutes for e in s.elements.all())
        s.minutes = minutes_realisees(s)
        s.minutes_texte = duree(s.minutes)
        s.activites = [e.title for e in s.elements.all() if ACTIVITE.match(e.title)]
    return seances


def _filtrer(request, seances):
    q = (request.GET.get('q') or '').strip()
    if q:
        seances = seances.filter(
            Q(lesson__title__icontains=q) | Q(elements__title__icontains=q) | Q(elements__partie__icontains=q)
            | Q(elements__sous_titre__icontains=q) | Q(observations__icontains=q)
            | Q(classroom__name__icontains=q)).distinct()
    du, au = _lire_date(request.GET.get('du')), _lire_date(request.GET.get('au'))
    if du:
        seances = seances.filter(date__gte=du)
    if au:
        seances = seances.filter(date__lte=au)
    classe = request.GET.get('classe')
    if classe and classe.isdigit():
        seances = seances.filter(classroom_id=int(classe))
    return seances, {'q': q, 'du': du, 'au': au, 'classe': classe or ''}


@teacher_required
def index(request):
    """Une carte par niveau scolaire (niveaux des cours enregistrés), avec le nombre de séances."""
    user = request.edubac_user
    ancienne_classe = request.GET.get('classe')
    if ancienne_classe and ancienne_classe.isdigit():       # anciens liens « ?classe= »
        classe = Classroom.objects.filter(pk=int(ancienne_classe)).first()
        if classe and classe.niveau in NIVEAUX:
            return redirect(reverse('cahier:niveau', args=[classe.niveau]) + f'?classe={classe.pk}')
    visibles = seances_visibles(user)
    comptes = dict(visibles.order_by().values_list('lesson__course__niveau').annotate(n=Count('id')))
    presents = set(Course.objects.values_list('niveau', flat=True)) | set(comptes)
    niveaux = [{'code': code, 'nom': nom, 'icone': ICONES.get(code, 'bi-journal-bookmark'),
                'nombre': comptes.get(code, 0)}
               for code, nom in Course.NIVEAU_CHOICES if code in presents]
    return render(request, 'cahier/index.html', {
        'page_title': 'Cahier de textes', 'niveaux': niveaux, 'total': sum(comptes.values()),
        'directeur': est_directeur(user),
        'classes_acces': (Classroom.objects.order_by('name') if user.is_staff or user.is_superuser
                          else Classroom.objects.filter(teacher=user).order_by('name')),
    })


@teacher_required
def niveau(request, niveau):
    nom = _niveau_ou_404(niveau)
    user = request.edubac_user
    toutes = seances_visibles(user).filter(lesson__course__niveau=niveau)
    seances, filtres = _filtrer(request, toutes)
    page = Paginator(seances, 15).get_page(request.GET.get('page'))
    preparer(page.object_list)
    _progression(page.object_list)
    classes = Classroom.objects.filter(pk__in=toutes.values('classroom')).order_by('name')
    pour_suivi = toutes
    if filtres['classe'].isdigit():
        pour_suivi = pour_suivi.filter(classroom_id=int(filtres['classe']))
    suivis = suivi_des_lecons(list(pour_suivi.order_by('date')))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'cahier/niveau.html', {
        'page_title': f'Cahier de textes — {nom}', 'niveau': niveau, 'nom': nom, 'page': page,
        'total': toutes.count(), 'trouvees': page.paginator.count, 'filtres': filtres, 'classes': classes,
        'params': params.urlencode(), 'directeur': est_directeur(user), 'moi': user.pk,
        'filtre_actif': any(filtres[k] for k in ('q', 'du', 'au', 'classe')),
        'suivis': suivis,
    })


def _reponse_pdf(contenu, nom_fichier):
    reponse = HttpResponse(contenu, content_type='application/pdf')
    reponse['Content-Disposition'] = f'attachment; filename="{nom_fichier}"'
    return reponse


@teacher_required
@require_GET
def seance_pdf(request, pk):
    user = request.edubac_user
    seance = get_object_or_404(seances_visibles(user), pk=pk)
    niveau = seance.lesson.course.niveau
    contenu = document(preparer([seance]), NIVEAUX.get(niveau, niveau), avec_enseignant=est_directeur(user),
                       titre_fichier=f'Séance du {seance.date:%d/%m/%Y}')
    return _reponse_pdf(contenu, f'seance-{seance.date:%Y-%m-%d}-{seance.pk}.pdf')


@teacher_required
@require_GET
def niveau_pdf(request, niveau):
    """?ids=… : les séances choisies ; sinon toutes les séances du niveau (avec couverture)."""
    nom = _niveau_ou_404(niveau)
    user = request.edubac_user
    seances = seances_visibles(user).filter(lesson__course__niveau=niveau).order_by('date', 'created_at', 'pk')
    ids = [int(i) for i in request.GET.getlist('ids') if i.isdigit()]
    selection = bool(request.GET.getlist('ids'))
    if selection:
        seances = seances.filter(pk__in=ids)
    seances = list(seances)
    if not seances:
        raise Http404
    contenu = document(preparer(seances), nom, couverture=not selection, avec_enseignant=est_directeur(user),
                       titre_fichier=f'Cahier de textes — {nom}')
    quoi = 'selection' if selection else 'complet'
    return _reponse_pdf(contenu, f'cahier-de-textes-{niveau}-{quoi}.pdf')


@teacher_required
@require_POST
def observations(request, pk):
    """Seul l'enseignant de la séance complète ses observations et sa durée réalisée."""
    seance = get_object_or_404(Seance.objects.select_related('lesson__course'), pk=pk, teacher=request.edubac_user)
    champs = ['updated_at']
    if 'observations' in request.POST:
        seance.observations = (request.POST.get('observations') or '').strip()[:4000]
        champs.append('observations')
    if 'duree' in request.POST:
        try:
            minutes = lire_duree(request.POST.get('duree'))
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(reverse('cahier:niveau', args=[seance.lesson.course.niveau]) + f'#seance-{seance.pk}')
        if minutes is not None:
            seance.duree_minutes = minutes
            champs.append('duree_minutes')
    seance.save(update_fields=champs)
    messages.success(request, 'Séance mise à jour.')
    return redirect(reverse('cahier:niveau', args=[seance.lesson.course.niveau]) + f'#seance-{seance.pk}')


@teacher_required
@require_POST
def supprimer(request, pk):
    seance = get_object_or_404(Seance.objects.select_related('lesson__course'), pk=pk, teacher=request.edubac_user)
    niveau = seance.lesson.course.niveau
    classe, lesson = seance.classroom, seance.lesson
    seance.delete()
    from . import acces
    acces.recalculer(classe, lesson)
    messages.success(request, 'Séance supprimée du cahier de textes.')
    return redirect('cahier:niveau', niveau=niveau)


# ─── Accès des élèves aux leçons ─────────────────────────────────────────────

def _classe_geree(user, pk):
    classe = get_object_or_404(Classroom, pk=pk)
    if classe.teacher_id != user.pk and not (user.is_staff or user.is_superuser):
        raise Http404
    return classe


def _lecons_du_niveau(classe):
    return list(Lesson.objects.filter(course__niveau=classe.niveau)
                .select_related('course').order_by('course__order', 'order', 'pk'))


@teacher_required
def acces_lecons(request, pk):
    """Leçons ouvertes ou verrouillées pour les élèves d'une classe, avec l'avancement du cahier."""
    from . import acces
    from .models import AccesLecon
    user = request.edubac_user
    classe = _classe_geree(user, pk)
    lecons = _lecons_du_niveau(classe)
    if request.method == 'POST':
        action = request.POST.get('action')
        lecon = next((l for l in lecons if str(l.pk) == request.POST.get('lecon')), None)
        if lecon is None:
            messages.error(request, 'Leçon inconnue pour cette classe.')
        elif action == 'jusqua':
            cibles = lecons[:lecons.index(lecon) + 1]
            for l in cibles:
                acces.decider(classe, l, AccesLecon.OUVERT, user)
            messages.success(request, f'{len(cibles)} leçon(s) ouvertes aux élèves de {classe.name}.')
        elif action in ('ouvrir', 'fermer', 'auto'):
            decision = {'ouvrir': AccesLecon.OUVERT, 'fermer': AccesLecon.FERME, 'auto': ''}[action]
            etat_ = acces.decider(classe, lecon, decision, user)
            messages.success(request, f'« {lecon.title} » : '
                             + ('ouverte aux élèves.' if etat_.est_ouverte else 'verrouillée pour les élèves.'))
        else:
            messages.error(request, 'Action inconnue.')
        if lecon and request.POST.get('retour') == 'lecon':
            return redirect('education:lesson_detail', pk=lecon.pk)
        return redirect(reverse('cahier:acces', args=[classe.pk]) + (f'#lecon-{lecon.pk}' if lecon else ''))
    lignes_acces = {a.lesson_id: a for a in AccesLecon.objects.filter(classroom=classe)}
    lignes = []
    for lecon in lecons:
        faites, total = acces.avancement(classe, lecon)
        a = lignes_acces.get(lecon.pk)
        lignes.append({
            'lecon': lecon, 'faites': faites, 'total': total,
            'pourcent': round(100 * faites / total) if total else None,
            'ouverte': bool(a and a.est_ouverte),
            'decision': a.decision if a else '',
            'termine_auto': bool(a and a.termine_auto),
        })
    return render(request, 'cahier/acces.html', {
        'classe': classe, 'lignes': lignes,
        'classes': Classroom.objects.filter(teacher=user).order_by('name')
                   if not (user.is_staff or user.is_superuser) else Classroom.objects.order_by('name'),
        'page_title': f'Accès des élèves — {classe.name}',
    })
