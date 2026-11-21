"""Plan d'un cours HTML (templates/education/cours/…) : parties (section.chap), sous-titres
(h3) et blocs (Définition, Proposition, Exemples, Applications…). Chaque élément reçoit une
clé stable tirée de sa position : « s1-b3 » = 3e bloc de la partie s1."""
import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings

from education.media_library import course_html_template

_cache = {}


class _Lecteur(HTMLParser):
    VIDES = {'br', 'img', 'hr', 'input', 'meta', 'link', 'path', 'line', 'circle', 'rect',
             'polygon', 'polyline', 'ellipse', 'use', 'source', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pile = []          # balises ouvertes : (tag, rôle)
        self.parties = []
        self.capture = None     # ('num' | 'h3' | 'tag', texte accumulé)

    def handle_starttag(self, tag, attrs):
        if tag in self.VIDES:
            return
        a = dict(attrs)
        classes = (a.get('class') or '').split()
        role = None
        if tag == 'section' and 'chap' in classes and a.get('id'):
            role = 'partie'
            self.parties.append({'key': a['id'], 'toc': (a.get('data-toc') or '').strip(), 'num': '',
                                 'enfants': [], 'blocs': 0, 'titres': 0})
        elif self.parties and self.dans('partie'):
            partie = self.parties[-1]
            if tag == 'span' and 'num' in classes and self.dernier_tag() == 'h2':
                role = 'num'
                self.capture = ['num', '']
            elif tag == 'h3' and not self.dans('bloc'):
                role = 'h3'
                self.capture = ['h3', '']
            elif tag == 'div' and 'bloc' in classes and not self.dans('bloc'):
                role = 'bloc'
                partie['blocs'] += 1
                partie['bloc_courant'] = {'key': f"{partie['key']}-b{partie['blocs']}", 'type': 'bloc',
                                          'titre': '', 'genre': next((c for c in classes if c != 'bloc'), '')}
            elif tag == 'div' and 'tag' in classes and self.dernier_role() == 'bloc':
                role = 'tag'
                self.capture = ['tag', '']
        self.pile.append((tag, role))

    def handle_endtag(self, tag):
        if tag in self.VIDES:
            return
        if self.capture is not None:
            self.capture[1] += ' '      # « <span>I.1</span>Titre » → « I.1 Titre »
        while self.pile:
            t, role = self.pile.pop()
            self.fermer(role)
            if t == tag:
                break

    def fermer(self, role):
        if not role or not self.parties:
            return
        partie = self.parties[-1]
        texte = re.sub(r'\s+', ' ', self.capture[1]).strip() if self.capture else ''
        if role == 'num':
            partie['num'] = texte
        elif role == 'h3':
            partie['titres'] += 1
            partie['enfants'].append({'key': f"{partie['key']}-t{partie['titres']}", 'type': 'titre',
                                      'titre': texte, 'enfants': []})
        elif role == 'tag':
            partie['bloc_courant']['titre'] = texte
        elif role == 'bloc':
            bloc = partie.pop('bloc_courant')
            parent = partie['enfants'][-1] if partie['enfants'] and partie['enfants'][-1]['type'] == 'titre' else None
            (parent['enfants'] if parent else partie['enfants']).append(bloc)
        if role in ('num', 'h3', 'tag'):
            self.capture = None

    def handle_data(self, data):
        if self.capture is not None:
            self.capture[1] += data

    def dans(self, role):
        return any(r == role for _, r in self.pile)

    def dernier_tag(self):
        return self.pile[-1][0] if self.pile else None

    def dernier_role(self):
        return self.pile[-1][1] if self.pile else None


def _numeroter(enfants):
    """« Exemples », « Exemples » sous le même titre → « Exemples (1) », « Exemples (2) »."""
    vus = {}
    for e in enfants:
        if e['type'] == 'bloc':
            vus[e['titre']] = vus.get(e['titre'], 0) + 1
    rang = {}
    for e in enfants:
        if e['type'] == 'bloc' and vus[e['titre']] > 1:
            rang[e['titre']] = rang.get(e['titre'], 0) + 1
            e['titre'] = f"{e['titre']} ({rang[e['titre']]})"
        if e['type'] == 'titre':
            _numeroter(e['enfants'])


def plan_du_fichier(chemin):
    chemin = Path(chemin)
    cle = (str(chemin), chemin.stat().st_mtime)
    if cle not in _cache:
        lecteur = _Lecteur()
        lecteur.feed(chemin.read_text(encoding='utf-8'))
        parties = []
        for p in lecteur.parties:
            _numeroter(p['enfants'])
            titre = f"{p['num']}. {p['toc']}" if p['num'] else p['toc']
            parties.append({'key': p['key'], 'type': 'partie', 'titre': titre, 'enfants': p['enfants']})
        _cache.clear()
        _cache[cle] = parties
    return _cache[cle]


def plan_de_lecon(lesson):
    """Plan du cours HTML de la leçon, ou None si la leçon n'a pas de cours HTML."""
    template = course_html_template(lesson)
    if template is None:
        return None
    return plan_du_fichier(Path(settings.BASE_DIR) / 'templates' / template)


def elements(plan):
    """Éléments cochables (feuilles), dans l'ordre du cours, avec leur contexte :
    les blocs, et les sous-titres ou parties qui n'ont aucun bloc."""
    liste = []

    def visiter(noeud, partie, sous_titre):
        enfants = noeud.get('enfants') or []
        if noeud['type'] == 'bloc' or not enfants:
            liste.append({'key': noeud['key'], 'titre': noeud['titre'], 'partie': partie['titre'],
                          'sous_titre': sous_titre['titre'] if sous_titre else '', 'ordre': len(liste)})
            return
        for e in enfants:
            visiter(e, partie, noeud if noeud['type'] == 'titre' else sous_titre)

    for p in plan:
        visiter(p, p, None)
    return liste
