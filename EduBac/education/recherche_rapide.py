"""Recherche rapide (bouton micro flottant) : pages de l'application, cours, leçons et paragraphes
des cours en ligne. Insensible aux accents et à la casse ; comprend quelques mots arabes courants
(la reconnaissance vocale en arabe donne « الجداء السلمي » pour « produit scalaire »)."""
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from .models import Course, Lesson

# Mots sans intérêt dans une phrase dictée : « ouvre-moi la page du cahier de textes ».
MOTS_VIDES = {
    'ouvrir', 'ouvre', 'ouvrez', 'ouvremoi', 'moi', 'aller', 'va', 'vas', 'allez', 'montre', 'montrer',
    'affiche', 'afficher', 'cherche', 'chercher', 'recherche', 'rechercher', 'trouve', 'trouver',
    'je', 'veux', 'voudrais', 'voir', 'page', 'la', 'le', 'les', 'l', 'de', 'du', 'des', 'd', 'un', 'une',
    'a', 'au', 'aux', 'sur', 'et', 'en', 'svp', 'stp', 's', 'il', 'te', 'plait', 'mon', 'ma', 'mes',
    'افتح', 'افتحي', 'اذهب', 'الى', 'إلى', 'صفحة', 'اريد', 'أريد', 'ابحث', 'عن', 'في', 'من', 'لي',
}

# Arabe → français (avant la mise en mots). Les expressions longues d'abord.
ARABE = [
    ('الجداء السلمي', 'produit scalaire'), ('جداء سلمي', 'produit scalaire'),
    ('الحساب المثلثي', 'trigonometrique'), ('حساب مثلثي', 'trigonometrique'),
    ('الأعداد الصحيحة الطبيعية', 'entiers naturels'), ('الهندسة الفضائية', 'geometrie espace'),
    ('دفتر النصوص', 'cahier textes'), ('لوحة التحكم', 'tableau bord'), ('السبورة', 'whiteboard'),
    ('المتتاليات', 'suites'), ('متتاليات', 'suites'), ('النهايات', 'limites'), ('نهايات', 'limites'),
    ('الاشتقاق', 'derivation'), ('اشتقاق', 'derivation'), ('المرجح', 'barycentre'), ('مرجح', 'barycentre'),
    ('الدوران', 'rotation'), ('دوران', 'rotation'), ('المنطق', 'logique'), ('منطق', 'logique'),
    ('المتجهات', 'vecteurs'), ('متجهات', 'vecteurs'), ('الفضاء', 'espace'), ('الحدوديات', 'polynomes'),
    ('حدوديات', 'polynomes'), ('المعادلات', 'equations'), ('معادلات', 'equations'),
    ('المتراجحات', 'inequations'), ('الإحصاء', 'statistiques'), ('احصاء', 'statistiques'),
    ('الإسقاط', 'projection'), ('اسقاط', 'projection'), ('المستقيم', 'droite'), ('الدوال', 'fonctions'),
    ('دوال', 'fonctions'), ('الدالة', 'fonction'), ('الترتيب', 'ordre'), ('الحسابيات', 'arithmetique'),
    ('المجموعات', 'ensembles'), ('التحويلات', 'transformations'), ('المثلثات', 'trigonometrie'),
    ('تعريف', 'definition'), ('خاصية', 'propriete'), ('مبرهنة', 'theoreme'), ('أمثلة', 'exemples'),
    ('الواجبات', 'devoirs'), ('واجب', 'devoir'), ('تمارين', 'exercices'), ('تمرين', 'exercice'), ('المحادثة', 'messagerie'), ('محادثة', 'messagerie'),
    ('الرسائل', 'messagerie'), ('الدردشة', 'messagerie'), ('الأقسام', 'classes'), ('القسم', 'classe'),
    ('التلاميذ', 'eleves'), ('الكويز', 'quiz'), ('كويز', 'quiz'), ('النتائج', 'resultats'),
    ('الدروس', 'cours'), ('الدرس', 'cours'), ('المستوى', 'niveau'), ('المفضلة', 'favoris'),
    ('الإعدادات', 'parametres'), ('الملف الشخصي', 'profil'), ('الترتيب العام', 'classement'),
]

# Pages : (nom d'URL, libellé, icône, mots-clés supplémentaires, pour qui).
TOUS, ELEVE, PROF, VISITEUR = 'tous', 'eleve', 'prof', 'visiteur'
PAGES = [
    ('education:home', 'Accueil', 'house-door', 'debut', TOUS),
    ('education:niveaux', 'Niveaux et leçons', 'layers', 'niveau scolaire lecons programme', TOUS),
    ('education:about', 'À propos', 'info-circle', '', TOUS),
    ('education:help', 'Aide', 'question-circle', 'guide utilisation', TOUS),
    ('education:contact', 'Contact', 'envelope', 'ecrire', TOUS),
    ('education:bac', 'Repères Bac', 'mortarboard', 'examen baccalaureat', TOUS),
    ('accounts:login', 'Connexion', 'box-arrow-in-right', 'se connecter login', VISITEUR),
    ('accounts:register', 'Inscription', 'person-plus', "s'inscrire creer compte", VISITEUR),
    ('accounts:dashboard', 'Tableau de bord', 'speedometer2', 'accueil', PROF),
    ('accounts:dashboard', 'Tableau de bord', 'speedometer2', '', ELEVE),
    ('accounts:my_courses', 'Mes cours', 'book', 'lecons', ELEVE),
    ('accounts:favorites', 'Favoris', 'star', 'favori', ELEVE),
    ('quizzes:assigned', 'Mes quiz', 'journal-check', 'devoirs controle', ELEVE),
    ('quizzes:my_results', 'Mes résultats', 'bar-chart', 'notes', ELEVE),
    ('quizzes:review_mistakes', 'Revoir mes erreurs', 'arrow-repeat', 'erreurs fautes reviser corriger', ELEVE),
    ('accounts:progress', 'Ma progression', 'graph-up', 'progres', ELEVE),
    ('accounts:badges', 'Badges', 'award', '', ELEVE),
    ('quizzes:ranking', 'Classement', 'trophy', '', ELEVE),
    ('accounts:calendar', 'Calendrier', 'calendar3', 'agenda', ELEVE),
    ('classrooms:list', 'Ma classe', 'people', 'classes', ELEVE),
    ('chat:home', 'Messagerie', 'chat-dots', 'chat discussion messages conversation', ELEVE),
    ('classrooms:list', 'Mes classes', 'people', 'classe', PROF),
    ('classrooms:students', 'Mes élèves', 'person-badge', 'eleve', PROF),
    ('classrooms:rapport', 'Rapport de la semaine', 'clipboard-data', 'hebdomadaire bilan', PROF),
    ('quizzes:manage', 'Mes quiz', 'pencil-square', 'gestion', PROF),
    ('quizzes:teacher_ai', 'Importer un quiz', 'upload', 'json generer', PROF),
    ('quizzes:student_results', 'Résultats des élèves', 'bar-chart-line', 'notes', PROF),
    ('quizzes:teacher_stats', 'Statistiques', 'graph-up-arrow', '', PROF),
    ('chat:home', 'Messagerie', 'chat-dots', 'chat discussion messages conversation', PROF),
    ('chat:moderation', 'Modération', 'shield-check', '', PROF),
    ('cahier:index', 'Cahier de textes', 'journal-bookmark', 'seance', PROF),
    ('quizzes:training', 'Entraînement', 'bullseye', '', PROF),
    ('devoirs:index', 'Devoirs', 'journal-arrow-down', 'devoir maison corrections', ELEVE),
    ('devoirs:index', 'Devoirs', 'journal-arrow-down', 'devoir maison corrections', PROF),
    ('devoirs:creer', 'Nouveau devoir', 'journal-plus', 'publier devoir', PROF),
    ('ai:assistant', 'Assistant IA', 'robot', 'intelligence artificielle', PROF),
    ('whiteboard:list', 'Whiteboard', 'easel', 'tableau blanc', ELEVE),
    ('whiteboard:list', 'Whiteboard', 'easel', 'tableau blanc', PROF),
    ('accounts:profile', 'Paramètres', 'gear', 'profil compte mot passe', ELEVE),
    ('accounts:profile', 'Paramètres', 'gear', 'profil compte mot passe', PROF),
]

MAX_PAR_TYPE = {'page': 5, 'cours': 4, 'lecon': 6, 'paragraphe': 8}


def normaliser(texte):
    """« Inégalité  de Cauchy-Schwarz » → « inegalite de cauchy schwarz »."""
    texte = unicodedata.normalize('NFKD', texte or '')
    texte = ''.join(c for c in texte if not unicodedata.combining(c)).lower()
    texte = re.sub(r'\\\(|\\\)|\\[a-z]+', ' ', texte)           # restes de LaTeX
    return ' '.join(re.findall(r'[a-z0-9]+|[؀-ۿ]+', texte))


def mots_de_la_requete(q):
    q = q or ''
    for ar, fr in ARABE:
        q = q.replace(ar, f' {fr} ')
    mots = [m for m in normaliser(q).split() if m not in MOTS_VIDES]
    return mots[:8]


def mots_du_texte(texte):
    """Tous les mots utiles d'un texte (sans limite) : énoncés, règles."""
    return [m for m in normaliser(texte).split() if m not in MOTS_VIDES]


def _mot_trouve(mot, texte):
    """Un mot de la requête est trouvé s'il commence un mot du texte (« deriv » → « derivation »)
    ou, pour les mots de 4 lettres et plus, s'il y figure (« scalaire » ⊂ « produitscalaire »)."""
    if re.search(r'(?:^| )' + re.escape(mot), texte):
        return True
    return len(mot) >= 4 and mot in texte


def score(mots, libelle, contexte=''):
    """0 si un mot manque ou si aucun mot n'est dans le libellé ; sinon plus c'est précis, plus c'est haut."""
    if not mots:
        return 0
    lib = normaliser(libelle)
    ctx = normaliser(contexte)
    dans_libelle = 0
    for mot in mots:
        if _mot_trouve(mot, lib):
            dans_libelle += 1
        elif not _mot_trouve(mot, ctx):
            return 0
    if not dans_libelle:
        return 0
    requete = ' '.join(mots)
    lib_sans_vides = ' '.join(m for m in lib.split() if m not in MOTS_VIDES)
    points = 10 * dans_libelle
    if lib_sans_vides == requete:
        points += 100                       # c'est exactement ça
    elif lib_sans_vides.startswith(requete):
        points += 40
    elif requete in lib_sans_vides:
        points += 25
    # Un libellé court qui contient tout est plus précis qu'un long.
    points += max(0, 20 - len(lib_sans_vides.split()) * 2) if dans_libelle == len(mots) else 0
    return points


# ---------- Paragraphes des cours en ligne (plan lu une fois par fichier modifié) ----------
_plans = {}


class _TextesDesBlocs(HTMLParser):
    """Texte de chaque bloc (« s2-b3 » : 3e bloc de premier niveau de la partie s2, comme cours.js
    et le cahier de textes), pour trouver un mot qui n'est pas dans un titre."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partie, self.n, self.profondeur, self.cle = '', 0, 0, None
        self.textes = {}
        self.ignore = 0          # texte des figures (SVG), scripts, boutons : hors du texte lisible

    IGNOREES = {'svg', 'figure', 'script', 'style', 'button'}

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNOREES:
            self.ignore += 1
            return
        a = dict(attrs)
        classes = (a.get('class') or '').split()
        if tag == 'section' and 'chap' in classes and a.get('id'):
            self.partie, self.n = a['id'], 0
        elif tag == 'div' and self.cle:
            self.profondeur += 1
        elif tag == 'div' and 'bloc' in classes and self.partie:
            self.n += 1
            self.cle, self.profondeur = f'{self.partie}-b{self.n}', 1
            self.textes[self.cle] = []

    def handle_endtag(self, tag):
        if tag in self.IGNOREES:
            self.ignore = max(0, self.ignore - 1)
            return
        if tag == 'div' and self.cle:
            self.profondeur -= 1
            if not self.profondeur:
                self.cle = None

    def handle_data(self, data):
        if self.cle and not self.ignore:
            self.textes[self.cle].append(data)


def _lisible(texte):
    from cahier.rubriques import _sans_tex
    texte = texte.replace('\\|', '‖').replace('\\{', '{').replace('\\}', '}')
    return re.sub(r'\s+', ' ', _sans_tex(texte)).strip()


def extrait(texte, mots, avant=6, apres=10):
    """« … les vecteurs u et v sont orthogonaux si et seulement si … » autour du premier mot trouvé."""
    morceaux = texte.split()
    normes = [normaliser(m) for m in morceaux]
    for i, n in enumerate(normes):
        if any(n.startswith(m) or len(m) >= 4 and m in n for m in mots):
            debut, fin = max(0, i - avant), min(len(morceaux), i + apres)
            return ('… ' if debut else '') + ' '.join(morceaux[debut:fin]) + (' …' if fin < len(morceaux) else '')
    return ''


def _paragraphes(lesson, owners):
    from cahier.rubriques import plan_du_fichier
    from .media_library import chapter_relative, course_html_template
    template = course_html_template(lesson, relative=chapter_relative(lesson, owners))
    if template is None:
        return []
    chemin = Path(settings.BASE_DIR) / 'templates' / template
    cle = (str(chemin), chemin.stat().st_mtime)
    if _plans.get(chemin) and _plans[chemin][0] == cle:
        return _plans[chemin][1]
    liste = []

    def visiter(noeud, partie):
        titre = (noeud.get('titre') or '').strip()
        if titre and noeud['type'] in ('partie', 'titre', 'bloc'):
            if noeud['type'] == 'bloc':
                titre = re.sub(r'\s*\(\d+\)$', '', titre)       # « Exemples (2) » → « Exemples »
            liste.append({'cle': noeud['key'], 'titre': titre, 'genre': noeud['type'],
                          'nature': noeud.get('genre', ''),
                          'partie': partie if noeud['type'] != 'partie' else ''})
        for enfant in noeud.get('enfants') or []:
            visiter(enfant, partie)

    for partie in plan_du_fichier(chemin):
        visiter(partie, partie['titre'])
    lecteur = _TextesDesBlocs()
    lecteur.feed(chemin.read_text(encoding='utf-8'))
    for p in liste:
        brut = lecteur.textes.get(p['cle'])
        if brut:
            p['source'] = ' '.join(' '.join(brut).split())       # avec le LaTeX d'origine
            p['texte'] = _lisible(' '.join(brut))
            p['texte_norm'] = normaliser(p['texte'])
    _plans[chemin] = (cle, liste)
    return liste


def _proprietaires(lecons):
    """Comme chapter_relative sans une requête par leçon : la première leçon (ordre des cours) de
    chaque (niveau, numéro, titre) possède le dossier du chapitre."""
    from django.utils.text import slugify
    owners = {}
    for l in sorted(lecons, key=lambda l: (l.course.order, l.course_id, l.pk)):
        owners.setdefault((l.course.niveau, l.order, slugify(l.title)[:160] or 'lecon'), l.pk)
    return owners


def _role(user):
    if not user:
        return VISITEUR
    return PROF if user.is_teacher() else ELEVE


def _niveaux_du_lecteur(user):
    """Niveaux à faire passer en premier : celui de l'élève (profil et classes), ceux des classes du professeur."""
    if not user:
        return set()
    from classrooms.models import Classroom
    if user.is_teacher():
        return set(Classroom.objects.filter(teacher=user).values_list('niveau', flat=True))
    niveaux = set(Classroom.objects.filter(members__user=user).values_list('niveau', flat=True))
    profil = getattr(user, 'student_profile', None) if hasattr(user, 'student_profile') else None
    if profil and profil.niveau:
        niveaux.add(profil.niveau)
    return niveaux


def rechercher(request, q, lecon=None):
    """Résultats triés du plus précis au moins précis, et « direct » : l'adresse où aller sans
    rien demander quand une seule réponse s'impose (dictée « messagerie », « produit scalaire »)."""
    from cahier.acces import peut_voir

    mots = mots_de_la_requete(q)
    if not mots or sum(len(m) for m in mots) < 2:
        return {'mots': mots, 'resultats': [], 'direct': None}
    user = getattr(request, 'edubac_user', None)
    role = _role(user)
    trouves = []
    vues = set()
    niveaux = _niveaux_du_lecteur(user)
    for nom, libelle, icone, extra, pour in PAGES:
        if pour not in (TOUS, role) or (nom, libelle) in vues:
            continue
        s = score(mots, f'{libelle} {extra}')
        if s:
            vues.add((nom, libelle))
            trouves.append({'type': 'page', 'titre': libelle, 'detail': 'Page', 'icone': icone,
                            'url': reverse(nom), 'score': s + 5})
    for course in Course.objects.all():
        s = score(mots, course.name, course.get_niveau_display())
        if s:
            s += 15 if course.niveau in niveaux else 0
            trouves.append({'type': 'cours', 'titre': course.name, 'detail': course.get_niveau_display(),
                            'icone': 'book', 'url': reverse('education:course_detail', args=[course.pk]),
                            'score': s})
    lecons = list(Lesson.objects.select_related('course').defer('content', 'summary', 'faq')
                  .order_by('course__niveau', 'course__order', 'order'))
    owners = _proprietaires(lecons)
    for lesson in lecons:
        niveau = lesson.course.get_niveau_display()
        verrou = not peut_voir(request, lesson)
        bonus = 15 if lesson.course.niveau in niveaux else 0
        if lecon and lesson.pk == lecon:
            bonus += 30          # recherche lancée depuis ce cours : ses fiches d'abord
        s = score(mots, lesson.title, f'{lesson.course.name} {niveau}')
        if s:
            trouves.append({'type': 'lecon', 'titre': lesson.title, 'detail': f'Leçon · {niveau}',
                            'icone': 'journal-text', 'verrou': verrou, 'score': s + 3 + bonus,
                            'url': reverse('education:lesson_detail', args=[lesson.pk])})
        base = reverse('education:lesson_course_html', args=[lesson.pk])
        for p in _paragraphes(lesson, owners):
            s = score(mots, p['titre'], f"{p['partie']} {lesson.title}")
            texte = ''
            # Mot seulement dans le texte d'un bloc : en dessous des titres, avec un extrait.
            # Jamais pour une leçon verrouillée (l'extrait dévoilerait le cours avant la séance).
            if not s and not verrou and p.get('texte_norm') and all(_mot_trouve(m, p['texte_norm']) for m in mots):
                s = 4 + 3 * len(mots)
                texte = extrait(p['texte'], mots)
            if s:
                chemin = ' › '.join(x for x in (lesson.title, p['partie']) if x)
                trouves.append({'type': 'paragraphe', 'titre': p['titre'], 'detail': chemin,
                                'icone': 'bookmark', 'verrou': verrou, 'score': s + bonus,
                                'url': f"{base}#{p['cle']}", **({'extrait': texte} if texte else {})})
    trouves.sort(key=lambda r: -r['score'])
    par_type, resultats = {}, []
    for r in trouves:
        par_type[r['type']] = par_type.get(r['type'], 0) + 1
        if par_type[r['type']] <= MAX_PAR_TYPE[r['type']]:
            resultats.append(r)
    direct = None
    if resultats and not resultats[0].get('verrou'):
        premier = resultats[0]['score']
        second = resultats[1]['score'] if len(resultats) > 1 else 0
        ecart = premier - second
        if (premier >= 100 and ecart >= 20 or len(resultats) == 1 and premier >= 30
                or resultats[0]['type'] != 'paragraphe' and premier >= 70 and ecart >= 15):
            direct = resultats[0]['url']
    return {'mots': mots, 'resultats': resultats, 'direct': direct}


def paragraphe_le_plus_proche(lesson, texte, owners=None):
    """Adresse de la fiche du cours en ligne qui parle le plus de « texte » (une règle, un énoncé),
    ou None. Sert au lien « Revoir dans le cours » des statistiques et de la révision des erreurs."""
    mots = {m for m in mots_du_texte(texte or '') if len(m) >= 4 and not m.isdigit()}
    if not mots:
        return None
    meilleur, score_max = None, 1
    for p in _paragraphes(lesson, owners):
        cible = normaliser(p['titre']) + ' ' + p.get('texte_norm', '')
        score = sum(1 for m in mots if _mot_trouve(m, cible))
        if p['genre'] == 'bloc' and p.get('nature') in {'def', 'prop', 'thm', 'meth'}:
            score += 0.5        # à égalité, une règle plutôt qu'un exemple
        if score > score_max:
            meilleur, score_max = p, score
    if meilleur is None:
        return None
    return reverse('education:lesson_course_html', args=[lesson.pk]) + '#' + meilleur['cle']
