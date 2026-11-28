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


# Guide de connexion des élèves (à imprimer) : captures de téléphone, repères numérotés.
# Positions des repères en % de la capture (bord droit du champ, milieu vertical).
GUIDE_REPERES = {
    'inscription': [
        ('1', 94.5, 36.3, 'الاسم الكامل', 'اكتب اسمك الشخصي ثم اسمك العائلي بالحروف اللاتينية، كما هو مسجّل في القسم.', 'Amal Bennani'),
        ('2', 94.5, 44.8, 'اسم المستخدم', 'اسم تختاره أنت لتدخل به إلى التطبيق، ويمكن أن يختلف عن اسمك. بدون مسافات وبدون حروف عربية. احفظه جيداً.', 'amal.bennani'),
        ('3', 94.5, 53.2, 'رمز القسم', 'الرمز الذي يعطيك إياه أستاذك (حروف وأرقام). يربط حسابك بقسمك.', ''),
        ('4', 94.5, 61.7, 'كلمة المرور', '6 أحرف على الأقل. اضغط على العين لترى ما كتبت.', ''),
        ('5', 94.5, 70.2, 'تأكيد كلمة المرور', 'أعد كتابة نفس كلمة المرور.', ''),
        ('6', 94.5, 88.1, 'إرسال الطلب', 'اضغط هنا لإرسال طلب التسجيل. يُفعَّل حسابك بعد موافقة الإدارة.', ''),
        ('7', 92.0, 95.1, 'لديك حساب؟', 'إذا كان لديك حساب من قبل، اضغط على «Connexion».', ''),
    ],
    'envoyee': [
        ('1', 97.0, 22.2, 'تم إرسال الطلب', 'تظهر هذه الصفحة بعد التسجيل: طلبك في انتظار موافقة الإدارة.', ''),
        ('2', 89.4, 44.7, 'اسم المستخدم', 'هذا هو الاسم الذي ستدخل به. اكتبه أو صوّره، وانتبه للحروف الكبيرة والصغيرة.', ''),
        ('3', 89.4, 71.6, 'نبّهني', 'اضغط على «Me prévenir» ثم «Autoriser»: يصلك إشعار على الهاتف عند قبول طلبك.', ''),
        ('4', 94.5, 92.7, 'الدخول لاحقاً', 'بعد القبول اضغط هنا، أو افتح الموقع من جديد واذهب إلى صفحة الدخول.', ''),
    ],
    'connexion': [
        ('1', 94.5, 45.4, 'اسم المستخدم', 'اكتب اسم المستخدم الذي اخترته عند التسجيل، بنفس الحروف الكبيرة والصغيرة.', 'amal.bennani'),
        ('2', 94.5, 56.8, 'كلمة المرور', 'اكتب كلمة المرور. اضغط على العين لتتأكد مما كتبت.', ''),
        ('3', 66.0, 65.4, 'تذكّرني', 'ضع علامة لتبقى متصلاً، فقط على هاتفك الشخصي.', ''),
        ('4', 62.0, 70.7, 'نسيت كلمة المرور؟', 'اكتب اسمك الكامل وقسمك، فتعطيك الإدارة كلمة مرور جديدة.', ''),
        ('5', 94.5, 80.4, 'الدخول', 'اضغط هنا للدخول إلى التطبيق.', ''),
        ('6', 97.0, 91.7, 'ليس لديك حساب؟', 'اضغط على «Inscription élève» للتسجيل أولاً.', ''),
    ],
}


def guide_eleves(request):
    """Guide imprimable (3 pages A4) : inscription, demande envoyée, connexion.
    L'adresse du site est celle de la page ouverte : toujours la bonne, sans réglage."""
    reperes = {
        cle: [{'n': n, 'x': x, 'y': y, 'titre': t, 'texte': d, 'exemple': e} for n, x, y, t, d, e in lignes]
        for cle, lignes in GUIDE_REPERES.items()
    }
    return render(request, 'education/info/guide_eleves.html', {
        'reperes': reperes,
        'adresse': request.build_absolute_uri('/'),
        'page_title': 'Guide de connexion des élèves',
    })
