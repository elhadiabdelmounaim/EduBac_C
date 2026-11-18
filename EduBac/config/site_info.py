"""Informations sur l'éditeur du site, affichées dans les pages légales et la page Contact.

Seul fichier à modifier pour mettre à jour ces informations. Une valeur vide
s'affiche « à compléter » (et la page signale à l'administrateur ce qui manque).
"""

SITE_INFO = {
    # Personne responsable du site et de la publication (nom et prénom).
    'publisher_name': '',
    # Adresse e-mail de contact affichée aux visiteurs.
    'contact_email': '',
    # Ville (et pays) de l'éditeur.
    'city': '',
    'country': 'Maroc',
    # Hébergeur du site.
    'host_name': 'PythonAnywhere (Anaconda, Inc.)',
    'host_url': 'https://www.pythonanywhere.com',
    # Date de dernière mise à jour des pages légales.
    'legal_updated': '18 novembre 2026',
}

# Dates officielles des examens de l'année scolaire en cours (facultatif).
# Exemple : {'label': 'Examen national — session normale', 'dates': '2 au 5 juin 2027'}
# Laisser vide tant que le Ministère ne les a pas publiées.
BAC_DATES = []

REQUIRED_FIELDS = {
    'publisher_name': 'nom du responsable',
    'contact_email': 'e-mail de contact',
    'city': 'ville',
}


def missing_fields():
    return [label for key, label in REQUIRED_FIELDS.items() if not str(SITE_INFO.get(key) or '').strip()]
