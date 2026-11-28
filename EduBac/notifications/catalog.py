"""Catalogue des types de notifications et préférences par défaut.

Chaque type a deux canaux réglables par l'utilisateur :
- « dans EduBac » : la notification compte dans le badge (sinon elle est rangée
  directement comme lue, mais reste visible dans l'historique) ;
- « e-mail » : immédiat, résumé quotidien, ou jamais.
"""

EMAIL_INSTANT = 'instant'
EMAIL_DIGEST = 'digest'
EMAIL_OFF = 'off'
EMAIL_CHOICES = [
    (EMAIL_INSTANT, 'Immédiat'),
    (EMAIL_DIGEST, 'Résumé quotidien'),
    (EMAIL_OFF, 'Jamais'),
]

TYPES = {
    'quiz_assigned': {
        'label': 'Quiz assignés et rappels',
        'icon': 'bi-clipboard-check',
        'roles': {'student'},
        'email': {'student': EMAIL_INSTANT},
    },
    'quiz_result': {
        'label': 'Résultats de quiz',
        'icon': 'bi-bar-chart',
        'roles': {'student', 'teacher'},
        # Le professeur reçoit une notification regroupée par quiz, et un résumé par e-mail.
        'email': {'student': EMAIL_INSTANT, 'teacher': EMAIL_DIGEST},
    },
    'quiz_missed': {
        'label': 'Quiz non faits après la date limite',
        'icon': 'bi-hourglass-bottom',
        'roles': {'teacher'},
        'email': {'teacher': EMAIL_DIGEST},
    },
    'devoir': {
        'label': 'Devoirs (nouveaux, rappels, corrections)',
        'icon': 'bi-journal-arrow-down',
        'roles': {'student'},
        'email': {'student': EMAIL_INSTANT},
    },
    'devoir_rendu': {
        'label': 'Devoirs rendus par les élèves',
        'icon': 'bi-inbox',
        'roles': {'teacher'},
        'email': {'teacher': EMAIL_DIGEST},
    },
    'rapport': {
        'label': 'Rapport hebdomadaire des classes',
        'icon': 'bi-clipboard-data',
        'roles': {'teacher'},
        'email': {'teacher': EMAIL_INSTANT},
    },
    'comment': {
        'label': 'Commentaires du professeur',
        'icon': 'bi-chat-square-text',
        'roles': {'student'},
        'email': {'student': EMAIL_INSTANT},
    },
    'message': {
        'label': 'Messagerie (annonces, consultations, messages privés)',
        'icon': 'bi-chat-dots',
        'roles': {'student', 'teacher'},
        'email': {'student': EMAIL_OFF, 'teacher': EMAIL_DIGEST},
    },
    'classroom': {
        'label': 'Vie de la classe (nouveaux élèves, tableaux partagés)',
        'icon': 'bi-people',
        'roles': {'student', 'teacher'},
        'email': {'student': EMAIL_OFF, 'teacher': EMAIL_DIGEST},
    },
    'moderation': {
        'label': 'Signalements de messages',
        'icon': 'bi-shield-exclamation',
        'roles': {'teacher'},
        'email': {'teacher': EMAIL_INSTANT},
    },
    'account': {
        'label': 'Compte et inscriptions',
        'icon': 'bi-person-check',
        'roles': {'student', 'teacher'},
        'email': {'student': EMAIL_INSTANT, 'teacher': EMAIL_INSTANT},
    },
    'system': {
        'label': 'Informations de la plateforme',
        'icon': 'bi-info-circle',
        'roles': {'student', 'teacher'},
        'email': {'student': EMAIL_OFF, 'teacher': EMAIL_OFF},
    },
    # Types historiques conservés pour les données existantes.
    'lesson': {'label': 'Leçons', 'icon': 'bi-journal-text', 'roles': set(), 'email': {}},
    'ai': {'label': 'Assistant IA', 'icon': 'bi-robot', 'roles': set(), 'email': {}},
}

TYPE_CHOICES = [(code, spec['label']) for code, spec in TYPES.items()]


def role_of(user):
    """Rôle utilisé pour les préférences : l'administration est traitée comme l'équipe pédagogique."""
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return 'teacher'
    return 'teacher' if getattr(user, 'role', '') == 'teacher' else 'student'


def types_for(user):
    role = role_of(user)
    return [code for code, spec in TYPES.items() if role in spec['roles']]


def default_preference(user, type_code):
    spec = TYPES.get(type_code, TYPES['system'])
    return {'in_app': True, 'email': spec['email'].get(role_of(user), EMAIL_OFF)}


def icon_for(type_code):
    return TYPES.get(type_code, TYPES['system'])['icon']
