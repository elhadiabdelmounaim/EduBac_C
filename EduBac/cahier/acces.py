"""Accès des élèves aux leçons : une leçon (cours, PDF, exercices) ne s'ouvre à une classe
qu'une fois traitée — automatiquement quand le cahier de textes couvre tout son plan, ou sur
décision du professeur. Professeurs et administration voient tout ; visiteurs : rien."""
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import AccesLecon, SeanceElement


def _utilisateur(request_ou_user):
    user = getattr(request_ou_user, 'edubac_user', request_ou_user)
    return user if getattr(user, 'pk', None) else None


def voit_tout(user):
    return bool(user and user.is_teacher())


def lecons_ouvertes(request_ou_user):
    """Identifiants des leçons ouvertes à l'utilisateur, ou None s'il voit tout.
    Mémorisé sur la requête : une seule requête par page, même pour une longue liste."""
    cache = getattr(request_ou_user, '_lecons_ouvertes', False)
    if cache is not False:
        return cache
    user = _utilisateur(request_ou_user)
    if voit_tout(user):
        resultat = None
    elif user is None:
        resultat = frozenset()
    else:
        from classrooms.models import ClassroomMember
        classes = ClassroomMember.objects.filter(user=user).values('classroom_id')
        resultat = frozenset(
            AccesLecon.objects.filter(classroom_id__in=classes)
            .filter(Q(decision=AccesLecon.OUVERT) | Q(decision='', termine_auto=True))
            .values_list('lesson_id', flat=True)
        )
    if hasattr(request_ou_user, 'META'):
        request_ou_user._lecons_ouvertes = resultat
    return resultat


def peut_voir(request_ou_user, lesson):
    ouvertes = lecons_ouvertes(request_ou_user)
    return ouvertes is None or getattr(lesson, 'pk', lesson) in ouvertes


def cles_du_plan(lesson):
    from .rubriques import elements, plan_de_lecon
    plan = plan_de_lecon(lesson)
    return {e['key'] for e in elements(plan)} if plan else set()


def avancement(classroom, lesson, cles=None):
    """(éléments traités du plan, total) pour cette classe, toutes séances confondues."""
    cles = cles_du_plan(lesson) if cles is None else cles
    faites = set(SeanceElement.objects.filter(
        seance__classroom=classroom, seance__lesson=lesson, key__in=cles,
    ).values_list('key', flat=True))
    return len(faites), len(cles)


def _ouvrir_si_besoin(acces, avant):
    """Première ouverture : date et notification aux élèves de la classe (une seule fois,
    même si le professeur verrouille puis rouvre la leçon)."""
    if acces.est_ouverte and not avant and acces.ouverte_le is None:
        acces.ouverte_le = timezone.now()
        acces.save(update_fields=['ouverte_le', 'updated_at'])
        notifier_ouverture(acces)


def recalculer(classroom, lesson):
    """Après un enregistrement ou une suppression dans le cahier de textes."""
    faites, total = avancement(classroom, lesson)
    termine = bool(total) and faites >= total
    acces = AccesLecon.objects.filter(classroom=classroom, lesson=lesson).first()
    if acces is None:
        if not termine:
            return None
        acces = AccesLecon(classroom=classroom, lesson=lesson)
    avant = bool(acces.pk) and acces.est_ouverte
    if acces.pk and acces.termine_auto == termine:
        return acces
    acces.termine_auto = termine
    acces.save()
    _ouvrir_si_besoin(acces, avant)
    return acces


def decider(classroom, lesson, decision, user):
    """Décision du professeur : 'ouvert', 'ferme' ou '' (revenir à l'automatique)."""
    if decision not in (AccesLecon.OUVERT, AccesLecon.FERME, ''):
        raise ValueError('Décision inconnue.')
    acces, _ = AccesLecon.objects.get_or_create(classroom=classroom, lesson=lesson)
    avant = acces.est_ouverte
    if decision == '':
        faites, total = avancement(classroom, lesson)
        acces.termine_auto = bool(total) and faites >= total
    acces.decision = decision
    acces.decide_par = user
    acces.save()
    _ouvrir_si_besoin(acces, avant)
    return acces


def notifier_ouverture(acces):
    from notifications.models import Notification
    eleves = [m.user for m in acces.classroom.members.select_related('user') if m.user.is_student()]
    Notification.notify_many(
        eleves,
        title='Nouveau cours disponible',
        message=f'Le cours « {acces.lesson.title} » est maintenant disponible : cours, PDF et exercices.',
        type='classroom',
        link=reverse('education:lesson_detail', args=[acces.lesson_id]),
        group_key=f'lecon-ouverte:{acces.classroom_id}:{acces.lesson_id}',
    )
