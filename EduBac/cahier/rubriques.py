"""Plan d'un cours HTML (templates/education/cours/…) : parties (section.chap), sous-titres
(h3) et blocs (Définition, Proposition, Exemples, Applications…). Chaque élément reçoit une
clé stable tirée de sa position : « s1-b3 » = 3e bloc de la partie s1."""
import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings

from education.media_library import course_html_template

_cache = {}


_SYMB = {'alpha': 'α', 'beta': 'β', 'pi': 'π', 'infty': '∞', 'le': '≤', 'ge': '≥', 'neq': '≠',
         'times': '×', 'cdot': '·', 'circ': '∘', 'mapsto': '↦', 'to': '→', 'Omega': 'Ω', 'omega': 'ω',
         'lambda': 'λ', 'theta': 'θ', 'Delta': 'Δ', 'sqrt': '√', 'cos': 'cos', 'sin': 'sin', 'tan': 'tan',
         'pm': '±', 'det': 'det', 'lim': 'lim'}


def _sans_tex(texte):
    """« Écrire \\(a\\cos x\\) » → « Écrire a cos x » : titres lisibles dans le cahier de textes."""
    if '\\' not in texte:
        return texte
    t = re.sub(r'\\[()\[\]]', ' ', texte)
    t = re.sub(r'\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}', r'\1/\2', t)
    t = re.sub(r'\\[dt]?frac\s*(\w)\s*(\w)', r' \1/\2', t)
    t = re.sub(r'\\([A-Za-z]+)', lambda m: ' ' + _SYMB.get(m.group(1), '') + ' ', t)
    t = t.replace('{', '').replace('}', '')
    t = re.sub(r'\s+([),;.])', r'\1', re.sub(r'([(])\s+', r'\1', t))
    return re.sub(r'\s+', ' ', t)


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
                                          'titre': '', 'genre': next((c for c in classes if c != 'bloc'), ''),
                                          'taille': 0, 'figures': 0, 'fixe': a.get('data-minutes')}
            elif tag in ('svg', 'figure') and self.dans('bloc') and 'bloc_courant' in partie \
                    and not self.dans('figure'):
                partie['bloc_courant']['figures'] += 1
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
        if self.capture is not None:
            self.capture[1] = _sans_tex(self.capture[1])
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
        elif self.parties and 'bloc_courant' in self.parties[-1] and self.dans('bloc'):
            self.parties[-1]['bloc_courant']['taille'] += len(re.sub(r'\s+', '', data))

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


# Temps relatif selon la nature du bloc : les applications sont faites par les élèves.
POIDS_GENRE = {'app': 2.0, 'act': 1.5, 'ex': 1.5, 'def': 1.0, 'prop': 1.0, 'meth': 1.0,
               'rem': 0.5, 'att': 0.5}
PAS = 5     # minutes


def _poids(feuille):
    if feuille['type'] != 'bloc':
        return 1.0
    volume = 1 + feuille.get('taille', 0) / 300 + 0.5 * feuille.get('figures', 0)
    return volume * POIDS_GENRE.get(feuille.get('genre'), 1.0)


def _feuilles(noeuds):
    for n in noeuds:
        if n['type'] == 'bloc' or not n.get('enfants'):
            yield n
        else:
            yield from _feuilles(n['enfants'])


def minuter(plan, total):
    """Répartit « total » minutes entre les éléments (par pas de 5 min, au prorata de leur
    poids). Un bloc portant data-minutes="30" garde sa durée ; les autres se partagent le
    reste. Chaque nœud reçoit « minutes » (somme de ses enfants pour un titre)."""
    feuilles = list(_feuilles(plan))
    fixes = {}
    for f in feuilles:
        try:
            fixes[f['key']] = max(0, int(f.get('fixe') or ''))
        except ValueError:
            pass
    libres = [f for f in feuilles if f['key'] not in fixes]
    reste = max(0, total - sum(fixes.values()))
    pas_dispo = reste // PAS
    poids = [_poids(f) for f in libres]
    somme = sum(poids) or 1
    parts = [p * pas_dispo / somme for p in poids]
    entiers = [max(1, int(x)) if pas_dispo >= len(libres) else int(x) for x in parts]
    # Plus forts restes, pour que la somme tombe juste.
    ordre = sorted(range(len(libres)), key=lambda i: parts[i] - int(parts[i]), reverse=True)
    k = 0
    while sum(entiers) < pas_dispo and ordre:
        entiers[ordre[k % len(ordre)]] += 1
        k += 1
    while sum(entiers) > pas_dispo:
        i = max(range(len(entiers)), key=lambda j: entiers[j])
        entiers[i] -= 1
    minutes = {f['key']: n * PAS for f, n in zip(libres, entiers)}
    if libres and reste % PAS:
        plus_long = max(libres, key=lambda f: minutes[f['key']])
        minutes[plus_long['key']] += reste % PAS
    minutes.update(fixes)

    def poser(n):
        if n['type'] == 'bloc' or not n.get('enfants'):
            n['minutes'] = minutes.get(n['key'], 0)
        else:
            n['minutes'] = sum(poser(e) for e in n['enfants'])
        return n['minutes']

    for p in plan:
        poser(p)
    return plan


def _nettoyer(noeuds):
    """Copie du plan sans les mesures internes (taille, figures…)."""
    return [{k: (_nettoyer(v) if k == 'enfants' else v) for k, v in n.items()
             if k not in ('taille', 'figures', 'fixe')} | ({'fixe': n['fixe']} if n.get('fixe') else {})
            for n in noeuds]


def plan_de_lecon(lesson):
    """Plan du cours HTML de la leçon (avec les minutes prévues si la répartition horaire
    connaît la leçon), ou None si la leçon n'a pas de cours HTML."""
    from education.repartition import repartition_de_lecon

    template = course_html_template(lesson)
    if template is None:
        return None
    brut = plan_du_fichier(Path(settings.BASE_DIR) / 'templates' / template)
    repartition = repartition_de_lecon(lesson)
    if repartition:
        plan = minuter(_copie(brut), int(round(repartition['heures'] * 60)))
        return _nettoyer(plan)
    return _nettoyer(brut)


def _copie(noeuds):
    return [{k: (_copie(v) if k == 'enfants' else v) for k, v in n.items()} for n in noeuds]


def elements(plan):
    """Éléments cochables (feuilles), dans l'ordre du cours, avec leur contexte :
    les blocs, et les sous-titres ou parties qui n'ont aucun bloc."""
    liste = []

    def visiter(noeud, partie, sous_titre):
        enfants = noeud.get('enfants') or []
        if noeud['type'] == 'bloc' or not enfants:
            liste.append({'key': noeud['key'], 'titre': noeud['titre'], 'partie': partie['titre'],
                          'sous_titre': sous_titre['titre'] if sous_titre else '', 'ordre': len(liste),
                          'minutes': noeud.get('minutes', 0)})
            return
        for e in enfants:
            visiter(e, partie, noeud if noeud['type'] == 'titre' else sous_titre)

    for p in plan:
        visiter(p, p, None)
    return liste
