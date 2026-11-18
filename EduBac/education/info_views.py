"""Pages d'information publiques : mentions légales, confidentialité, conditions,
contact, aide et repères du Bac."""
from django.shortcuts import render

from config.site_info import BAC_DATES, SITE_INFO, missing_fields

PAGES = {
    'legal': ('education/info/legal.html', 'Mentions légales',
              'Éditeur, hébergeur et propriété intellectuelle du site EduBac.'),
    'privacy': ('education/info/privacy.html', 'Confidentialité',
                'Quelles données EduBac collecte, pourquoi, combien de temps, et comment exercer vos droits.'),
    'terms': ('education/info/terms.html', 'Conditions d’utilisation',
              'Règles d’utilisation d’EduBac : compte, messagerie, contenus et responsabilités.'),
    'contact': ('education/info/contact.html', 'Contact',
                'Écrire au professeur ou à l’administrateur d’EduBac.'),
    'help': ('education/info/help.html', 'Aide',
             'Installer l’application, activer les notifications, passer un quiz, écrire au professeur.'),
    'bac': ('education/info/bac.html', 'Repères Bac',
            'Calcul de la note du Bac au Maroc, calendrier des examens et conseils de révision.'),
}


def _page(name):
    template, title, description = PAGES[name]

    def view(request):
        user = getattr(request, 'edubac_user', None)
        return render(request, template, {
            'page_title': title,
            'meta_description': description,
            'site': SITE_INFO,
            'bac_dates': BAC_DATES,
            'missing_info': missing_fields() if user and not user.is_student() else [],
            'info_pages': [(key, PAGES[key][1]) for key in ('help', 'bac', 'contact', 'legal', 'privacy', 'terms')],
            'current_page': name,
        })
    view.__name__ = f'info_{name}'
    return view


legal = _page('legal')
privacy = _page('privacy')
terms = _page('terms')
contact = _page('contact')
help_page = _page('help')
bac = _page('bac')
