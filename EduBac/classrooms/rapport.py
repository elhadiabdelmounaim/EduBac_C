"""Rapport de la semaine du professeur, classe par classe : élèves actifs, quiz faits et
moyenne, devoirs rendus. Affiché dans EduBac et envoyé le dimanche (commande rapport_hebdo)."""
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

JOURS = 7


def rapport_professeur(prof, fin=None):
    from accounts.models import User
    from devoirs.models import Devoir
    from quizzes.models import Attempt

    from .models import Classroom, ClassroomMember

    fin = fin or timezone.now()
    debut = fin - timedelta(days=JOURS)
    classes = []
    for classe in Classroom.objects.filter(teacher=prof, is_active=True).order_by('niveau', 'name'):
        ids = list(ClassroomMember.objects.filter(classroom=classe, user__role='student').values_list('user_id', flat=True))
        eleves = User.objects.filter(pk__in=ids)
        actifs = eleves.filter(derniere_activite__gte=debut).count()
        tentatives = Attempt.objects.filter(student_id__in=ids, submitted_at__gte=debut, submitted_at__lt=fin)
        stats = tentatives.aggregate(n=Count('pk'), moyenne=Avg('score'), eleves=Count('student', distinct=True))
        devoirs = []
        for devoir in (Devoir.objects.filter(classes=classe, rendu_en_ligne=True)
                       .filter(Q(date_limite__gte=debut, date_limite__lt=fin) | Q(cree_le__gte=debut))
                       .distinct().order_by('date_limite')):
            rendus = devoir.rendus.filter(eleve_id__in=ids).count()
            devoirs.append({'devoir': devoir, 'rendus': rendus, 'attendus': len(ids),
                            'manquants': len(ids) - rendus})
        classes.append({
            'classe': classe, 'eleves': len(ids), 'actifs': actifs, 'inactifs': len(ids) - actifs,
            'quiz_faits': stats['n'], 'quiz_eleves': stats['eleves'],
            'moyenne': round(stats['moyenne']) if stats['moyenne'] is not None else None,
            'devoirs': devoirs,
        })
    return {'debut': debut, 'fin': fin, 'classes': classes}


def resume_texte(rapport):
    """Quelques lignes pour la notification et l'e-mail."""
    lignes = []
    for c in rapport['classes']:
        morceaux = [f"{c['actifs']}/{c['eleves']} élèves actifs"]
        if c['quiz_faits']:
            morceaux.append(f"{c['quiz_faits']} quiz faits (moyenne {c['moyenne']} %)")
        manquants = sum(d['manquants'] for d in c['devoirs'])
        if c['devoirs']:
            morceaux.append(f"{manquants} copie{'s' if manquants > 1 else ''} manquante{'s' if manquants > 1 else ''}")
        lignes.append(f"{c['classe'].name} : " + ', '.join(morceaux))
    return ' · '.join(lignes)
