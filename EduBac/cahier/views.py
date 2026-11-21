"""Cahier de textes : enregistrement depuis le cours (panneau « Séance ») et consultation."""
import datetime
import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import teacher_required
from classrooms.models import Classroom
from education.models import Lesson

from education.repartition import repartition_de_lecon

from .models import Seance, SeanceElement
from .rubriques import elements, plan_de_lecon


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
        'cahier_url': reverse('cahier:index'),
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
            else:
                for k in cles:
                    data['deja'][k] = s.date.strftime('%d/%m')
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
    with transaction.atomic():
        seance, cree = Seance.objects.get_or_create(teacher=user, classroom=classe, lesson=lesson, date=jour)
        if not cree:
            seance.elements.all().delete()
            seance.save(update_fields=['updated_at'])
        SeanceElement.objects.bulk_create([
            SeanceElement(seance=seance, key=e['key'], title=e['titre'][:255], partie=e['partie'][:255],
                          sous_titre=e['sous_titre'][:255], order=e['ordre'], minutes=e['minutes'])
            for e in choisis
        ])
    return JsonResponse({
        'ok': True, 'cree': cree, 'nombre': len(choisis),
        'message': ('Séance enregistrée' if cree else 'Séance mise à jour')
                   + f' : {len(choisis)} élément{"s" if len(choisis) > 1 else ""}, le {jour:%d/%m/%Y}.',
        'url': reverse('cahier:index') + f'?classe={classe.pk}#seance-{seance.pk}',
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


def duree(minutes):
    """95 → « 1 h 35 » ; 40 → « 40 min »."""
    minutes = int(minutes or 0)
    if minutes < 60:
        return f'{minutes} min'
    h, m = divmod(minutes, 60)
    return f'{h} h {m:02d}' if m else f'{h} h'


def _progression(user, seances):
    """Pour chaque séance : temps prévu de tout ce qui a été traité dans cette leçon avec
    cette classe jusqu'à cette date (incluse), comparé aux heures de la répartition."""
    paires = {(s.classroom_id, s.lesson_id) for s in seances}
    if not paires:
        return
    historiques = {}
    for s in (Seance.objects.filter(teacher=user, classroom_id__in={c for c, _ in paires},
                                    lesson_id__in={le for _, le in paires})
              .prefetch_related('elements').order_by('date')):
        historiques.setdefault((s.classroom_id, s.lesson_id), []).append(s)
    for s in seances:
        repartition = repartition_de_lecon(s.lesson)
        vus = {}
        for h in historiques.get((s.classroom_id, s.lesson_id), []):
            if h.date > s.date:
                break
            for e in h.elements.all():
                vus[e.key] = e.minutes
        fait = sum(vus.values())
        s.progression = None
        if repartition:
            prevu = int(round(repartition['heures'] * 60))
            s.progression = {'fait': duree(fait), 'prevu': duree(prevu),
                             'pourcent': min(100, round(100 * fait / prevu)) if prevu else 0}


@teacher_required
def index(request):
    user = request.edubac_user
    classes = list(_classes(user))
    seances = (Seance.objects.filter(teacher=user)
               .select_related('classroom', 'lesson', 'lesson__course')
               .prefetch_related('elements'))
    classe = next((c for c in classes if str(c.pk) == request.GET.get('classe')), None)
    if classe:
        seances = seances.filter(classroom=classe)
    page = Paginator(seances, 20).get_page(request.GET.get('page'))
    _progression(user, page.object_list)
    for s in page.object_list:
        s.parties = _regrouper(s)
        s.minutes = sum(e.minutes for e in s.elements.all())
        s.minutes_texte = duree(s.minutes)
    return render(request, 'cahier/index.html', {
        'page_title': 'Cahier de textes', 'classes': classes, 'classe': classe, 'page': page,
    })


@teacher_required
@require_POST
def supprimer(request, pk):
    seance = get_object_or_404(Seance, pk=pk, teacher=request.edubac_user)
    classe = seance.classroom_id
    seance.delete()
    messages.success(request, 'Séance supprimée du cahier de textes.')
    return redirect(reverse('cahier:index') + f'?classe={classe}')
