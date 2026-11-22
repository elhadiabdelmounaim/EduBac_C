#!/usr/bin/env python3
"""Convertit un cours LaTeX (style commun des cours EduBac) en template HTML de cours en ligne.

Usage :
    python tools/tex2html.py cours.tex N sortie.html ["Libellé du niveau" DOSSIER "Volume horaire"]

    N        : numéro de chapitre affiché (l'ordre de la leçon sur le site)
    sortie   : templates/education/cours/<DOSSIER>/<NN_titre>.html (nom attendu par le site)
    exemple  : python tools/tex2html.py TC_Polynomes.tex 4 \
                   templates/education/cours/TCS/04_les-polynomes.html \
                   "Tronc commun scientifique" TCS "8 heures"

Sans les trois derniers arguments : 1ère Bac Sciences (1BAC_SE), volume horaire lu dans le .tex.
Les figures TikZ / pgfplots / tkz-tab sont redessinées en SVG ; les commandes non reconnues
sont signalées par « ! » en fin d'exécution. Outil hors application : aucune dépendance.
"""
import math
import re
import sys

WARN = []


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# --------------------------------------------------------------------------- lecture
def group(s, i, o='{', c='}'):
    if s[i] != o:
        raise ValueError('attendu %r : %r' % (o, s[i:i + 60]))
    d = 0
    j = i
    while j < len(s):
        ch = s[j]
        if ch == '\\':
            j += 2
            continue
        if ch == o:
            d += 1
        elif ch == c:
            d -= 1
            if d == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise ValueError('groupe non fermé : ' + s[i:i + 80])


def optarg(s, i):
    if i < len(s) and s[i] == '[':
        d = 0
        j = i + 1
        while j < len(s):
            ch = s[j]
            if ch == '\\':
                j += 2
                continue
            if ch == '{':
                d += 1
            elif ch == '}':
                d -= 1
            elif ch == ']' and d == 0:
                return s[i + 1:j], j + 1
            j += 1
    return None, i


def env_end(s, i, name):
    b, e = '\\begin{%s}' % name, '\\end{%s}' % name
    d, j = 1, i
    while True:
        nb, ne = s.find(b, j), s.find(e, j)
        if ne < 0:
            raise ValueError('fin manquante : ' + name)
        if 0 <= nb < ne:
            d += 1
            j = nb + len(b)
        else:
            d -= 1
            if d == 0:
                return ne, ne + len(e)
            j = ne + len(e)


def split_top(s, sep):
    """Découpe s sur sep hors accolades, hors $…$ et hors environnements."""
    parts, cur, d, env, math_, i = [], [], 0, 0, False, 0
    while i < len(s):
        if s.startswith('\\begin{', i):
            env += 1
        elif s.startswith('\\end{', i):
            env -= 1
        ch = s[i]
        if d == 0 and env == 0 and not math_ and s.startswith(sep, i):
            parts.append(''.join(cur))
            cur = []
            i += len(sep)
            continue
        if ch == '\\':
            cur.append(s[i:i + 2])
            i += 2
            continue
        if ch == '{':
            d += 1
        elif ch == '}':
            d -= 1
        elif ch == '$':
            math_ = not math_
        cur.append(ch)
        i += 1
    parts.append(''.join(cur))
    return parts


# --------------------------------------------------------------------------- macros
BLACKLIST = {'inter', 'Auteur', 'Niveau', 'Annee', 'sffamb', 'puce', 'coche', 'croix', 'ligneblanche',
             'entete', 'blanc', 'TitreCours', 'Semestre', 'cube',
             'EnteteCours', 'Partie', 'SousPartie'}


def macros_du_preambule(pre):
    m = {}
    for mt in re.finditer(r'\\newcommand\{\\(\w+)\}(?:\[(\d)\])?(\[[^\]]*\])?\{', pre):
        name, n = mt.group(1), int(mt.group(2) or 0)
        body, _ = group(pre, mt.end() - 1)
        if name not in BLACKLIST:
            m[name] = (n, body)
    return m


def expand(s, macros):
    pat = re.compile(r'\\([A-Za-z]+)')
    for _ in range(12):
        out, i, changed = [], 0, False
        while True:
            mt = pat.search(s, i)
            if not mt:
                out.append(s[i:])
                break
            name = mt.group(1)
            if name not in macros:
                out.append(s[i:mt.end()])
                i = mt.end()
                continue
            n, body = macros[name]
            j = mt.end()
            for k in range(n):
                while s[j] == ' ':
                    j += 1
                if s[j] == '{':
                    a, j = group(s, j)
                else:
                    a, j = s[j], j + 1
                body = body.replace('#%d' % (k + 1), a)
            if re.search(r'\\[A-Za-z]+$', body) and j < len(s) and s[j].isalpha():
                body += ' '
            out.append(s[i:mt.start()])
            out.append(body)
            i, changed = j, True
        s = ''.join(out)
        if not changed:
            break
    return s


# --------------------------------------------------------------------------- texte des figures
SYMB = {'pi': 'π', 'alpha': 'α', 'beta': 'β', 'theta': 'θ', 'omega': 'ω', 'Omega': 'Ω', 'Delta': 'Δ',
        'infty': '∞', 'times': '×', 'le': '≤', 'leq': '≤', 'ge': '≥', 'geq': '≥', 'cdot': '·',
        'circ': '∘', 'to': '→', 'neq': '≠', 'mapsto': '↦', 'pm': '±', 'cos': 'cos', 'sin': 'sin',
        'tan': 'tan', 'lim': 'lim', 'prime': '′', 'ell': 'ℓ', 'Gamma': 'Γ'}
SUP = str.maketrans('0123456789+-n', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ')
SUB = str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉')


def tex_svg(s):
    """TeX simple → contenu de <text> SVG (tspans pour indices et vecteurs)."""
    s = s.strip().strip('$')
    out = []
    i = 0

    def arg(j):
        while j < len(s) and s[j] == ' ':
            j += 1
        if j < len(s) and s[j] == '{':
            a, j = group(s, j)
            return a, j
        if s.startswith('\\', j):
            m = re.match(r'\\[A-Za-z]+', s[j:])
            return s[j:j + m.end()], j + m.end()
        return s[j:j + 1], j + 1

    while i < len(s):
        ch = s[i]
        if ch == '\\':
            m = re.match(r'\\([A-Za-z]+)|\\(.)', s[i:])
            name = m.group(1)
            i += m.end()
            if not name:
                out.append(' ' if m.group(2) in ',;: ' else esc(m.group(2) or ''))
            elif name in ('frac', 'dfrac', 'tfrac'):
                a, i = arg(i)
                b, i = arg(i)
                out.append(tex_svg(a) + '/' + tex_svg(b))
            elif name == 'sqrt':
                a, i = arg(i)
                t = tex_svg(a)
                out.append('√' + (t if len(a) <= 1 else '(' + t + ')'))
            elif name in ('vect', 'overrightarrow'):
                a, i = arg(i)
                out.append('<tspan text-decoration="overline">%s</tspan>' % tex_svg(a))
            elif name == 'vec':
                a, i = arg(i)
                out.append(tex_svg(a) + '\u20d7')
            elif name in ('mathcal',):
                a, i = arg(i)
                out.append({'C': '𝒞'}.get(a, a))
            elif name in ('mathbb',):
                a, i = arg(i)
                out.append({'R': 'ℝ', 'N': 'ℕ', 'Z': 'ℤ'}.get(a, a))
            elif name in ('text', 'mathrm', 'textbf', 'mbox'):
                a, i = arg(i)
                out.append(esc(a))
            elif name in SYMB:
                out.append(SYMB[name])
            elif name in ('left', 'right', 'big', 'Big', 'displaystyle', 'quad', 'qquad', 'scriptsize',
                          'small', 'tiny', 'sffamily', 'footnotesize', 'limits'):
                out.append(' ' if 'quad' in name else '')
            else:
                out.append('')
        elif ch in '^_':
            a, i = arg(i + 1)
            t = tex_svg(a)
            if ch == '^' and re.fullmatch(r'[0-9+\-n]+', a):
                out.append(a.translate(SUP))
            elif ch == '_' and re.fullmatch(r'[0-9]+', a):
                out.append(a.translate(SUB))
            else:
                out.append('<tspan baseline-shift="%s" font-size="72%%">%s</tspan>' %
                           ('super' if ch == '^' else 'sub', t))
        elif ch in '{}$':
            i += 1
        else:
            out.append('−' if ch == '-' else esc(ch))
            i += 1
    return ''.join(out)


# --------------------------------------------------------------------------- dessin SVG
COUL = {'white': 'var(--surface)', 'niveau': 'var(--fig-trait)', 'meth': 'var(--meth)', 'or': 'var(--fig-accent)',
        'gris': 'var(--doux)', 'alerte': 'var(--att)', 'prop': 'var(--prop)', 'appl': 'var(--app)',
        'white': 'var(--surface)', 'black': 'var(--texte)', 'gray': 'var(--trait)'}
FOND = {'niveauclair': 'var(--def-bg)', 'methclair': 'var(--meth-bg)', 'applclair': 'var(--app-bg)',
        'white': 'var(--surface)', 'propclair': 'var(--prop-bg)'}
TAILLE = {'tiny': 10, 'scriptsize': 11.5, 'footnotesize': 12.5, 'small': 13.5}
UID = [0]


def couleur(nom):
    base, _, pct = nom.partition('!')
    if base in FOND:
        return FOND[base], 1
    if base in COUL:
        return COUL[base], (int(pct) / 100 if pct.isdigit() else 1)
    return None, 1


def opts_list(o):
    return [x.strip() for x in split_top(o or '', ',') if x.strip()]


class Style:
    def __init__(self, opts, fill_cmd=False):
        self.stroke, self.fill, self.width, self.dash = 'var(--fig-trait)', None, 1.3, False
        self.arrow_end = self.arrow_start = False
        self.opacity, self.size, self.text = 1, 14, None
        self.pos = None
        self.has_color = None
        for o in opts_list(opts):
            k, _, v = o.partition('=')
            k = k.strip()
            v = v.strip()
            if k in ('thick',):
                self.width = 2
            elif k == 'very thick':
                self.width = 2.6
            elif k == 'thin':
                self.width = 1
            elif k == 'line width':
                self.width = 1.4 * float(re.sub('[a-z]', '', v))
            elif k in ('dashed', 'densely dashed'):
                self.dash = True
            elif k == 'draw' and v:
                self.stroke, _ = couleur(v)
            elif k == 'fill' and v:
                c, op = couleur(v)
                self.fill = c if not c or op >= 1 else 'color-mix(in srgb, %s %d%%, var(--surface))' % (c, round(op * 100))
            elif k == 'font':
                for n, t in TAILLE.items():
                    if n in v:
                        self.size = t
            elif '-' in k and 'Stealth' in k or k in ('->', '<->', '-latex'):
                self.arrow_end = k.endswith('}') or k.endswith('>')
                self.arrow_start = k.startswith('{') or k.startswith('<')
            elif k in ('above', 'below', 'left', 'right', 'above right', 'above left', 'below right',
                       'below left', 'anchor'):
                self.pos = v if k == 'anchor' else k
            else:
                c, op = couleur(k)
                if c:
                    self.has_color = c
                    if fill_cmd:
                        # Teinte claire : mélange avec le fond (des aplats superposés ne s'assombrissent pas).
                        self.fill = c if op >= 1 else 'color-mix(in srgb, %s %d%%, var(--surface))' % (c, round(op * 100))
                    else:
                        self.stroke = c
                        self.opacity = op
                    self.text = c


class Canvas:
    def __init__(self):
        UID[0] += 1
        self.id = 'g%d' % UID[0]
        self.items, self.markers = [], set()
        self.x0 = self.y0 = 1e9
        self.x1 = self.y1 = -1e9
        self.back = []

    def grow(self, x, y):
        self.x0, self.y0 = min(self.x0, x), min(self.y0, y)
        self.x1, self.y1 = max(self.x1, x), max(self.y1, y)

    def stroke_attrs(self, st, fill=None):
        a = 'fill="%s" stroke="%s" stroke-width="%.1f" stroke-linecap="round" stroke-linejoin="round"' % (
            fill or 'none', st.stroke if st.stroke else 'none', st.width)
        if st.dash:
            a += ' stroke-dasharray="5 4"'
        if st.opacity < 1:
            a += ' opacity="%.2f"' % st.opacity
        if st.arrow_end or st.arrow_start:
            mid = 'm%s-%d' % (self.id, abs(hash(st.stroke)) % 1000)
            self.markers.add((mid, st.stroke))
            if st.arrow_end:
                a += ' marker-end="url(#%s)"' % mid
            if st.arrow_start:
                a += ' marker-start="url(#%s)"' % mid
        return a

    def path(self, d, st, fill=None, pts=(), first=False):
        for x, y in pts:
            self.grow(x, y)
        el = '<path d="%s" %s/>' % (d, self.stroke_attrs(st, fill))
        (self.back if first else self.items).append(el)

    def circle(self, x, y, r, st, fill=None):
        self.grow(x - r, y - r)
        self.grow(x + r, y + r)
        self.items.append('<circle cx="%.1f" cy="%.1f" r="%.1f" %s/>' % (x, y, r, self.stroke_attrs(st, fill)))

    def ellipse(self, x, y, rx, ry, st, fill=None):
        self.grow(x - rx, y - ry)
        self.grow(x + rx, y + ry)
        self.items.append('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" %s/>' % (x, y, rx, ry, self.stroke_attrs(st, fill)))

    def text(self, x, y, label, pos=None, size=14, color=None):
        lignes = [l for l in re.split(r'\\\\', label) if l.strip()]
        if len(lignes) > 1:          # nœud « align=center » sur plusieurs lignes
            for k, l in enumerate(lignes):
                self.text(x, y + (k - (len(lignes) - 1) / 2) * size * 1.15, l, pos, size, color)
            return
        t = tex_svg(label)
        if not re.sub('<[^>]+>', '', t).strip():
            return
        n = len(re.sub('<[^>]+>', '', t))
        w = n * size * 0.55
        g = 5
        anchor, dx, dy = 'middle', 0, size * 0.35
        pos = (pos or '').replace('north', 'n').replace('south', 's').replace('east', 'e').replace('west', 'w')
        if pos in ('above', 's'):
            dy = -g
        elif pos in ('below', 'n'):
            dy = g + size * 0.8
        elif pos in ('left', 'e'):
            anchor, dx = 'end', -g
        elif pos in ('right', 'w'):
            anchor, dx = 'start', g
        elif pos in ('above right', 's w'):
            anchor, dx, dy = 'start', g * 0.7, -g * 0.7
        elif pos in ('above left', 's e'):
            anchor, dx, dy = 'end', -g * 0.7, -g * 0.7
        elif pos in ('below right', 'n w'):
            anchor, dx, dy = 'start', g * 0.7, g * 0.7 + size * 0.8
        elif pos in ('below left', 'n e'):
            anchor, dx, dy = 'end', -g * 0.7, g * 0.7 + size * 0.8
        x, y = x + dx, y + dy
        x0 = x - (w / 2 if anchor == 'middle' else (w if anchor == 'end' else 0))
        self.grow(x0, y - size)
        self.grow(x0 + w, y + size * 0.3)
        style = 'font-size:%.1fpx' % size
        if color:
            style += ';fill:%s' % color
        self.items.append('<text x="%.1f" y="%.1f" text-anchor="%s" style="%s">%s</text>' % (x, y, anchor, style, t))

    def svg(self, label='Figure'):
        m = 6
        x0, y0 = self.x0 - m, self.y0 - m
        w, h = self.x1 - self.x0 + 2 * m, self.y1 - self.y0 + 2 * m
        defs = ''.join(
            '<marker id="%s" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" '
            'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="%s"/></marker>' % (mid, c)
            for mid, c in sorted(self.markers))
        return ('<svg viewBox="%.1f %.1f %.1f %.1f" role="img" aria-label="%s">%s%s%s</svg>' % (
            x0, y0, w, h, esc(label), '<defs>%s</defs>' % defs if defs else '', ''.join(self.back),
            ''.join(self.items)))


def num(v):
    v = v.strip().strip('{}')
    f = 1
    for u, k in (('cm', 1), ('mm', 0.1), ('pt', 1 / 28.45)):
        if v.endswith(u):
            v, f = v[:-len(u)], k
    return float(eval(v, {'sqrt': math.sqrt, 'pi': math.pi, 'cos': lambda a: math.cos(math.radians(a)),
                          'sin': lambda a: math.sin(math.radians(a)),
                          'tan': lambda a: math.tan(math.radians(a))})) * f


# --------------------------------------------------------------------------- TikZ
def foreach_expand(s):
    while True:
        m = re.search(r'\\foreach\s+((?:\\\w+/?)+)\s+in\s*\{', s)
        if not m:
            return s
        lst, j = group(s, m.end() - 1)
        while s[j] in ' \n':
            j += 1
        if s[j] == '{':
            body, k = group(s, j)
        else:
            k = s.index(';', j) + 1
            body = s[j:k]
        names = [v.strip('\\') for v in m.group(1).split('/')]
        vals = [x.strip() for x in split_top(lst, ',') if x.strip()]
        if len(vals) == 3 and vals[1] == '...':
            vals = [str(v) for v in range(int(vals[0]), int(vals[2]) + 1)]
        out = []
        for v in vals:
            parts = v.split('/') if len(names) > 1 else [v]
            b = body
            for n, p in sorted(zip(names, parts), key=lambda t: -len(t[0])):
                b = re.sub(r'\\%s(?![A-Za-z])' % n, lambda _m, p=p: p, b)
            out.append(b + ';')
        s = s[:m.start()] + ''.join(out) + s[k:]


def statements(s):
    return [x.strip() for x in split_top(s, ';') if x.strip()]


class Tikz:
    def __init__(self, opt, axis=None):
        self.U = 40.0
        self.X, self.Y, self.Z = (1, 0), (0, 1), (-0.35, -0.35)
        self.names = {}
        self.axis = axis
        for o in opts_list(opt):
            k, _, v = o.partition('=')
            k = k.strip()
            if k == 'scale':
                self.U *= float(v)
            elif k == 'xscale':
                self.X = (self.X[0] * float(v), self.X[1])
            elif k == 'yscale':
                self.Y = (self.Y[0], self.Y[1] * float(v))
            elif k in ('x', 'y', 'z'):
                a = v.strip().strip('{}').strip('()').split(',')
                setattr(self, k.upper(), (num(a[0]), num(a[1])))

    def px(self, p):
        dx, dy = getattr(self, 'decalage', (0, 0))
        return ((p[0] + dx) * self.U, -(p[1] + dy) * self.U)

    def point(self, s):
        """s sans parenthèses externes → coordonnées « cm » (2D)."""
        s = s.strip()
        if s.startswith('$'):
            return self.calc(s.strip('$'))
        if s.startswith('axis cs:'):
            a = s[8:].split(',')
            return self.axis(num(a[0]), num(a[1]))
        if ':' in s and ',' not in s:
            a, r = s.split(':')
            a, r = num(a), num(r)
            return (r * math.cos(math.radians(a)), r * math.sin(math.radians(a)))
        if re.fullmatch(r'[A-Za-z][\w]*(\.\w+)?', s):
            return self.names[s.split('.')[0]]
        vals = [num(v) for v in split_top(s, ',')]
        if len(vals) == 3:
            x, y, z = vals
            return (x * self.X[0] + y * self.Y[0] + z * self.Z[0], x * self.X[1] + y * self.Y[1] + z * self.Z[1])
        return (vals[0], vals[1])

    def take_point(self, s, i):
        txt, j = group(s, i, '(', ')')
        return self.point(txt), j

    def calc(self, s):
        a, i = self.take_point(s, 0)
        s = s[i:].strip()
        if s[:1] in '+-' and s:
            while s[:1] in ('+', '-') and s:
                sg = 1 if s[0] == '+' else -1
                b, j = self.take_point(s, s.index('(', 1))
                a = (a[0] + sg * b[0], a[1] + sg * b[1])
                s = s[j:].strip()
            return a
        if s.startswith('!'):
            k = s.index('!', 1) if not s[1] == '(' else None
            if s[1] == '(':
                p, j = self.take_point(s, 1)
                b, _ = self.take_point(s, j + 1)
                dx, dy = b[0] - a[0], b[1] - a[1]
                t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
                return (a[0] + t * dx, a[1] + t * dy)
            t = num(s[1:k])
            rest = s[k + 1:]
            dist = re.search(r'(cm|mm|pt)\s*$', s[1:k])
            ang = 0
            m = re.match(r'([-\d.]+):', rest)
            if m:
                ang = float(m.group(1))
                rest = rest[m.end():]
            b, _ = self.take_point(rest, 0)
            if ang:
                c, sn = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                dx, dy = b[0] - a[0], b[1] - a[1]
                b = (a[0] + c * dx - sn * dy, a[1] + sn * dx + c * dy)
            if dist:                     # « !0.25cm! » : distance depuis a, pas une fraction
                ln = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
                t = t / ln
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        return a

    def run(self, body, cv):
        body = foreach_expand(body)
        body = re.sub(r'\\begin\{scope\}(\[[^\]]*\])?', lambda mm: ';\\scopedebut%s;' % (mm.group(1) or '[]'), body)
        body = body.replace('\\end{scope}', ';\\scopefin;')
        pile = []
        for st in statements(body):
            # \begin{scope}[xshift=…,yshift=…] … \end{scope} : décalage des coordonnées.
            while True:
                st = st.strip()
                mb = re.match(r'\\scopedebut', st)
                if mb:
                    o, j = optarg(st, mb.end())
                    pile.append(getattr(self, 'decalage', (0, 0)))
                    dx, dy = pile[-1]
                    for kv in opts_list(o):
                        k, _, v = kv.partition('=')
                        if k.strip() == 'xshift':
                            dx += num(v)
                        elif k.strip() == 'yshift':
                            dy += num(v)
                    self.decalage = (dx, dy)
                    st = st[j:]
                    continue
                me = re.match(r'\\scopefin', st)
                if me:
                    self.decalage = pile.pop() if pile else (0, 0)
                    st = st[me.end():]
                    continue
                break
            m = re.match(r'\\(coordinate|draw|fill|filldraw|node|path|addplot)\b', st)
            if not m:
                continue
            cmd = m.group(1)
            rest = st[m.end():].strip()
            opts, i = optarg(rest, 0)
            rest = rest[i:].strip()
            if cmd == 'coordinate':
                n = re.match(r'\((\w+)\)\s*at\s*', rest)
                p, _ = self.take_point(rest, n.end())
                self.names[n.group(1)] = p
            elif cmd == 'node':
                st_ = Style(opts)
                m2 = re.match(r'(\([^)]*\))?\s*at\s*', rest)
                if not m2:
                    continue
                p, j = self.take_point(rest, m2.end())
                txt, _ = group(rest, rest.index('{', j))
                x, y = self.px(p)
                cv.text(x, y, txt, st_.pos, st_.size, st_.text)
            elif cmd in ('draw', 'fill', 'filldraw', 'path'):
                self.path(cmd, opts, rest, cv)

    def path(self, cmd, opts, s, cv):
        st = Style(opts, fill_cmd=(cmd == 'fill'))
        fill = st.fill if cmd in ('fill', 'filldraw') or st.fill else None
        if cmd == 'fill' and 'draw=' not in (opts or ''):
            st.stroke = None
            fill = fill or 'var(--texte)'
        d, pts, cur, pending_mid = [], [], None, []
        start = None
        conn = None
        i = 0
        labels = []
        while i < len(s):
            if s[i] in ' \n\t':
                i += 1
                continue
            if s.startswith('++', i) or s.startswith('+(', i) or s[i] == '(':
                rel = s.startswith('++', i)
                rel1 = s.startswith('+(', i)
                if rel:
                    i += 2
                elif rel1:
                    i += 1
                p, i = self.take_point(s, i)
                if rel or rel1:
                    p = (cur[0] + p[0], cur[1] + p[1])
                x, y = self.px(p)
                if conn == 'line' and cur is not None:
                    d.append('L%.1f %.1f' % (x, y))
                elif conn and conn.startswith('bend') and cur is not None:
                    cx, cy = self.px(cur)
                    mx, my = (cx + x) / 2, (cy + y) / 2
                    ang = float(conn.split(':')[1])
                    k = math.tan(math.radians(ang)) / 2
                    qx, qy = mx - (y - cy) * k, my + (x - cx) * k
                    d.append('Q%.1f %.1f %.1f %.1f' % (qx, qy, x, y))
                elif conn == 'rect' and cur is not None:
                    cx, cy = self.px(cur)
                    d.append('L%.1f %.1f L%.1f %.1f L%.1f %.1f Z' % (x, cy, x, y, cx, y))
                    pts.append((cx, cy))
                else:
                    d.append('M%.1f %.1f' % (x, y))
                    start = (x, y)
                for lab in pending_mid:
                    a = self.px(cur)
                    labels.append(((a[0] + x) / 2, (a[1] + y) / 2, lab))
                pending_mid = []
                pts.append((x, y))
                cur, conn = p, None
            elif s.startswith('--', i):
                conn, i = 'line', i + 2
            elif s.startswith('to', i):
                o, i = optarg(s, i + 2)
                conn = 'line'
                if o and 'bend' in o:
                    mm = re.search(r'bend (left|right)=?([\d.]*)', o)
                    ang = float(mm.group(2) or 30) * (1 if mm.group(1) == 'left' else -1)
                    conn = 'bend:%f' % ang
            elif s.startswith('cycle', i):
                d.append('Z')
                i += 5
            elif s.startswith('rectangle', i):
                conn, i = 'rect', i + 9
            elif s.startswith('circle', i):
                i += 6
                while s[i] == ' ':
                    i += 1
                r, i = group(s, i, '(', ')')
                x, y = self.px(cur)
                rr = num(r) * self.U if not r.strip().endswith('pt') else num(r) * 40 * 1.0
                cv.circle(x, y, max(rr, 1.2), st, fill)
            elif s.startswith('plot', i):
                i += 4
                while s[i] == ' ':
                    i += 1
                expr, i = group(s, i, '(', ')')
                dm = re.search(r'domain=([-\d.]+):([-\d.]+)', opts or '')
                lo, hi = (float(dm.group(1)), float(dm.group(2))) if dm else (-5.0, 5.0)
                n = 40
                for t in range(n + 1):
                    xv = lo + (hi - lo) * t / n
                    q = self.point(re.sub(r'\\x(?![A-Za-z])', '(%r)' % xv, expr).replace('{', '(').replace('}', ')'))
                    x, y = self.px(q)
                    d.append(('M' if t == 0 else 'L') + '%.1f %.1f' % (x, y))
                    pts.append((x, y))
                    cur = q
            elif s.startswith('ellipse', i):
                i += 7
                while s[i] == ' ':
                    i += 1
                r, i = group(s, i, '(', ')')
                a, _, b = r.partition(' and ')
                x, y = self.px(cur)
                cv.ellipse(x, y, num(a) * self.U * abs(self.X[0]), num(b) * self.U * abs(self.Y[1]), st, fill)
            elif s.startswith('arc', i):
                i += 3
                while s[i] == ' ':
                    i += 1
                a, i = group(s, i, '(', ')')
                a0, a1, r = [num(v) for v in a.split(':')]
                c = (cur[0] - r * math.cos(math.radians(a0)), cur[1] - r * math.sin(math.radians(a0)))
                end = (c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1)))
                x, y = self.px(end)
                R = r * self.U
                large = 1 if abs(a1 - a0) > 180 else 0
                sweep = 0 if a1 > a0 else 1
                d.append('A%.1f %.1f 0 %d %d %.1f %.1f' % (R, R, large, sweep, x, y))
                for t in range(0, 11):
                    aa = math.radians(a0 + (a1 - a0) * t / 10)
                    pts.append(self.px((c[0] + r * math.cos(aa), c[1] + r * math.sin(aa))))
                cur = end
            elif s.startswith('node', i):
                o, j = optarg(s, i + 4)
                while s[j] == ' ':
                    j += 1
                txt, j = group(s, j)
                ns = Style(o)
                if conn == 'line':
                    pending_mid.append((txt, ns))
                else:
                    x, y = self.px(cur)
                    labels.append((x, y, (txt, ns)))
                i = j
            else:
                i += 1
        if d:
            cv.path(' '.join(d), st, fill if cmd != 'draw' or st.fill else None, pts,
                    first=(cmd == 'fill' and fill and st.stroke is None))
        for x, y, (txt, ns) in labels:
            cv.text(x, y, txt, ns.pos, ns.size, ns.text or (st.has_color if cmd != 'fill' else None))


# --------------------------------------------------------------------------- pgfplots
def pgf_eval(expr):
    e = expr.replace('^', '**').replace('deg(', '(')
    code = compile(e, 'expr', 'eval')
    env = {'sqrt': math.sqrt, 'sin': math.sin, 'cos': math.cos, 'tan': math.tan, 'pi': math.pi,
           'abs': abs, 'exp': math.exp, 'ln': math.log}

    def f(x):
        return eval(code, dict(env, x=x))
    return f


def ticks(v):
    if not v or '\\empty' in v:
        return []
    v = v.strip().strip('{}')
    vals = [x.strip() for x in v.split(',')]
    if '...' in vals:
        k = vals.index('...')
        a, b = float(vals[k - 1]), float(vals[k + 1])
        step = (a - float(vals[k - 2])) if k >= 2 else 1
        out = [float(x) for x in vals[:k - 1]]
        x = a
        while x <= b + 1e-9:
            out.append(round(x, 6))
            x += step
        return out
    return [float(x) for x in vals]


def fmt(v):
    s = ('%g' % v)
    return s.replace('-', '−')


def render_axis(body):
    m = re.search(r'\\begin\{axis\}', body)
    o, j = optarg(body, m.end())
    inner = body[j:env_end(body, j, 'axis')[0]]
    kv = {}
    for item in opts_list(o):
        k, _, v = item.partition('=')
        kv[k.strip()] = v.strip()
    W = num(kv.get('width', '6cm')) * 36
    H = num(kv.get('height', '5cm')) * 36
    xmin, xmax = float(kv['xmin']), float(kv['xmax'])
    ymin, ymax = float(kv['ymin']), float(kv['ymax'])

    def X(x):
        return (x - xmin) / (xmax - xmin) * W

    def Y(y):
        return H - (y - ymin) / (ymax - ymin) * H

    cv = Canvas()
    tk = Tikz('', axis=lambda x, y: (X(x) / 40, -Y(y) / 40))
    tk.U = 40
    xt, yt = ticks(kv.get('xtick')), ticks(kv.get('ytick'))
    xl = None
    if 'xticklabels' in kv:
        xl = [x.strip() for x in split_top(kv['xticklabels'].strip('{}'), ',')]
    grid = Style('gray')
    grid.width = 0.8
    for x in xt:
        cv.path('M%.1f 0 V%.1f' % (X(x), H), grid, pts=[(X(x), 0), (X(x), H)], first=True)
    for y in yt:
        cv.path('M0 %.1f H%.1f' % (Y(y), W), grid, pts=[(0, Y(y)), (W, Y(y))], first=True)
    ax = Style('gris,-{Stealth}')
    ax.width = 1.2
    y0 = Y(0) if ymin <= 0 <= ymax else H
    x0 = X(0) if xmin <= 0 <= xmax else 0
    cv.path('M0 %.1f H%.1f' % (y0, W), ax, pts=[(0, y0), (W, y0)])
    cv.path('M%.1f %.1f V0' % (x0, H), ax, pts=[(x0, H), (x0, 0)])
    if 'xlabel' in kv and kv['xlabel'].strip('{}') != '$x$':
        cv.text(W / 2, y0 + 30, kv['xlabel'].strip('{}'), None, 12, 'var(--doux)')
    else:
        cv.text(W, y0, '$x$', 'below left', 12, 'var(--doux)')
    if 'ylabel' in kv and kv['ylabel'].strip('{}') != '$y$':
        cv.text(x0 + 6, -10, kv['ylabel'].strip('{}'), 'right', 12, 'var(--doux)')
    else:
        cv.text(x0, 0, '$y$', 'right', 12, 'var(--doux)')
    if 'title' in kv:
        cv.text(W / 2, -30, re.sub(r'\\(scriptsize|small|footnotesize|tiny)\s*', '', kv['title'].strip('{}')).strip('{} '),
                None, 12, 'var(--doux)')
    for k, x in enumerate(xt):
        cv.text(X(x), y0, xl[k] if xl else fmt(x), 'below', 11, 'var(--doux)')
    for y in yt:
        cv.text(x0, Y(y), fmt(y), 'left', 11, 'var(--doux)')
    clip = 'c' + cv.id
    plots = []
    for stt in statements(foreach_expand(inner)):
        mm = re.match(r'\\addplot\b', stt)
        if not mm:
            sub = Canvas()
            sub.id = cv.id
            tk.run(stt + ';', cv)
            continue
        rest = stt[mm.end():].strip()
        po, i = optarg(rest, 0)
        st = Style(po)
        rest = rest[i:].strip()
        kvp = dict((a.partition('=')[0].strip(), a.partition('=')[2].strip()) for a in opts_list(po))
        if rest.startswith('coordinates'):
            pts_s, _ = group(rest, rest.index('{'))
            pts = [tuple(float(v) for v in p.split(',')) for p in re.findall(r'\(([^)]*)\)', pts_s)]
            if 'only marks' in (po or ''):
                r = float(re.sub('[a-z]', '', kvp.get('mark size', '2pt'))) * 1.3
                for x, y in pts:
                    cv.circle(X(x), Y(y), r, Style(po), fill=st.stroke)
                continue
            if 'ycomb' in (po or ''):          # diagramme en bâtons
                d = ' '.join('M%.1f %.1f V%.1f' % (X(x), Y(max(0, ymin)), Y(y)) for x, y in pts)
                st.width = max(st.width, 4)
                plots.append('<path d="%s" %s/>' % (d, cv.stroke_attrs(st).replace('stroke-linecap="round"', 'stroke-linecap="butt"')))
                continue
            if 'ybar interval' in (o or '') + (po or ''):   # histogramme
                for (xa, ya), (xb, _) in zip(pts, pts[1:]):
                    plots.append('<path d="M%.1f %.1f V%.1f H%.1f V%.1f Z" %s/>' % (
                        X(xa), Y(max(0, ymin)), Y(ya), X(xb), Y(max(0, ymin)),
                        cv.stroke_attrs(st, st.fill or 'var(--def-bg)')))
                continue
            d = 'M' + ' L'.join('%.1f %.1f' % (X(x), Y(y)) for x, y in pts)
            if 'mark=*' in (po or '').replace(' ', ''):
                r = float(re.sub('[a-z]', '', kvp.get('mark size', '2pt'))) * 1.3
                for x, y in pts:
                    cv.circle(X(x), Y(y), r, Style(po), fill=st.stroke)
        else:
            expr, _ = group(rest, rest.index('{'))
            f = pgf_eval(expr)
            a, b = [float(v) for v in kvp.get('domain', '%g:%g' % (xmin, xmax)).split(':')]
            n = max(int(kvp.get('samples', 60)), 120)
            d, prev = [], None
            for k in range(n + 1):
                x = a + (b - a) * k / n
                try:
                    y = f(x)
                except (ValueError, ZeroDivisionError):
                    prev = None
                    continue
                if abs(y) > 1e6:
                    prev = None
                    continue
                py = max(-H, min(2 * H, Y(y)))
                d.append(('L' if prev is not None else 'M') + '%.1f %.1f' % (X(x), py))
                prev = y
            d = ' '.join(d)
        plots.append('<path d="%s" %s clip-path="url(#%s)"/>' % (d, cv.stroke_attrs(st), clip))
    cv.items = plots + cv.items
    cv.grow(0, 0)
    cv.grow(W, H)
    svg = cv.svg()
    return svg.replace('<defs>', '<defs><clipPath id="%s"><rect x="-2" y="-2" width="%.1f" height="%.1f"/></clipPath>'
                       % (clip, W + 4, H + 4), 1) if '<defs>' in svg else svg.replace(
        '">', '"><defs><clipPath id="%s"><rect x="-2" y="-2" width="%.1f" height="%.1f"/></clipPath></defs>'
        % (clip, W + 4, H + 4), 1)


# --------------------------------------------------------------------------- tkz-tab
def render_tab(body):
    m = re.search(r'\\tkzTabInit', body)
    o, j = optarg(body, m.end())
    rows_s, j = group(body, j)
    xs_s, j = group(body, j)
    kv = dict((a.partition('=')[0].strip(), a.partition('=')[2].strip()) for a in opts_list(o))
    sp = float(kv.get('espcl', 2)) * 30
    rows = []
    for r in split_top(rows_s, ','):
        lab, _, h = r.rpartition('/')
        rows.append((lab.strip(), float(h or 1) * 26))
    xs = [x.strip() for x in split_top(xs_s, ',')]
    Lw, pad = 64, 22
    xpos = [Lw + pad + k * sp for k in range(len(xs))]
    W = xpos[-1] + pad
    tops = [0]
    for _, h in rows:
        tops.append(tops[-1] + h)
    cv = Canvas()
    frame = Style('niveau')
    frame.width = 1
    cv.path('M0 0 H%.1f V%.1f H0 Z' % (W, tops[-1]), frame, pts=[(0, 0), (W, tops[-1])])
    cv.path('M%d 0 V%.1f' % (Lw, tops[-1]), frame)
    for t in tops[1:-1]:
        cv.path('M0 %.1f H%.1f' % (t, W), frame)
    for k, (lab, h) in enumerate(rows):
        cv.text(Lw / 2, tops[k] + h / 2, lab, None, 13)
    for k, x in enumerate(xs):
        cv.text(xpos[k], tops[0] + rows[0][1] / 2, x, None, 13)
    row = 1
    for mt in re.finditer(r'\\tkzTab(Line|Var)\s*\{', body):
        content, _ = group(body, mt.end() - 1)
        top, h = tops[row], rows[row][1]
        cy = top + h / 2
        if mt.group(1) == 'Line':
            ent = [e.strip() for e in split_top(content, ',')]
            for k, e in enumerate(ent):
                x = xpos[k // 2] if k % 2 == 0 else (xpos[k // 2] + xpos[k // 2 + 1]) / 2
                if e == 'z':
                    cv.text(x, cy, '0', None, 13)
                    dsh = Style('gris,dashed')
                    dsh.width = 0.8
                    cv.path('M%.1f %.1f V%.1f' % (x, top, top + h * 0.22), dsh)
                    cv.path('M%.1f %.1f V%.1f' % (x, top + h * 0.78, top + h), dsh)
                elif e == 't':
                    dsh = Style('gris,dashed')
                    dsh.width = 0.8
                    cv.path('M%.1f %.1f V%.1f' % (x, top, top + h), dsh)
                elif e == 'd':
                    cv.path('M%.1f %.1f V%.1f M%.1f %.1f V%.1f' % (x - 2, top, top + h, x + 2, top, top + h), frame)
                elif e in ('+', '-'):
                    cv.text(x, cy, '+' if e == '+' else '−', None, 14)
                elif e and k % 2 == 1:
                    # Texte libre : « \text{signe de } {-a} » → « signe de −a ».
                    t = re.sub(r'\\text\{([^{}]*)\}', lambda mm: mm.group(1), e)
                    t = re.sub(r'\s+', ' ', t.replace('{', '').replace('}', '')).strip()
                    t = re.sub(r'(?<![\w])-(?=\w)', '−', t)
                    cv.text(x, cy, t, None, 12)
        else:
            ent = [e.strip() for e in split_top(content, ',')]
            ends = []          # (gauche, droite) : (y, x)
            for k, e in enumerate(ent):
                parts = [p.strip() for p in e.split('/')]
                code = parts[0]
                x = xpos[k]
                yt, yb = top + 13, top + h - 7

                def ypos(c):
                    return yt if c == '+' else yb
                if 'D' in code:
                    c1, c2 = code.split('D')
                    cv.path('M%.1f %.1f V%.1f M%.1f %.1f V%.1f' % (x - 2, top, top + h, x + 2, top, top + h), frame)
                    v1, v2 = parts[1], parts[2] if len(parts) > 2 else ''
                    if c1:
                        cv.text(x - 3, ypos(c1) - 4.5, v1, 'left', 13)
                    if c2:
                        cv.text(x + 3, ypos(c2) - 4.5, v2, 'right', 13)
                    left = (ypos(c1) if c1 else None, x - 14)
                    right = (ypos(c2) if c2 else None, x + 14)
                else:
                    v = parts[1] if len(parts) > 1 else ''
                    cv.text(x, ypos(code), v, None, 13)
                    left = (ypos(code), x - 12)
                    right = (ypos(code), x + 12)
                ends.append((left, right))
            arr = Style('niveau,-{Stealth}')
            arr.width = 1.2
            for k in range(len(ends) - 1):
                (y1, x1), (y2, x2) = ends[k][1], ends[k + 1][0]
                if y1 is None or y2 is None:
                    continue
                y1 += -4 if y1 > cy else 6
                y2 += -4 if y2 > cy else 6
                y1 = y1 - 6 if y1 > cy else y1
                y2 = y2 - 6 if y2 > cy else y2
                cv.path('M%.1f %.1f L%.1f %.1f' % (x1, y1, x2, y2), arr)
        row += 1
    return cv.svg('Tableau')


def render_tikz(opt, body):
    for m in list(re.finditer(r'\\def\\([A-Za-z]+)\{([^{}]*)\}', body)):
        body = body.replace(m.group(0), '')
        body = re.sub(r'\\%s(?![A-Za-z])' % m.group(1), lambda _m, v=m.group(2): v, body)
    if 'rotate around' in body:
        return None
    if 'node distance' in (opt or '') + body:
        return 'MATH'
    if '\\begin{axis}' in body:
        return render_axis(body)
    if '\\tkzTabInit' in body:
        return render_tab(body)
    cv = Canvas()
    Tikz(opt).run(body, cv)
    return cv.svg()


# --------------------------------------------------------------------------- conversion
BLOCS = {'activite': 'act', 'definition': 'def', 'propriete': 'prop', 'methode': 'meth',
         'remarque': 'rem', 'attention': 'att', 'exemple': 'ex', 'application': 'app', 'retenir': 'ret'}
TAG = {'definition': 'Définition', 'propriete': 'Propriété', 'methode': 'Méthode', 'remarque': 'Remarques',
       'attention': 'Attention — erreurs fréquentes', 'exemple': 'Exemples', 'retenir': 'À retenir'}
ARGS = {'minipage': 1, 'multicols': 1, 'tabular': 1, 'tabularx': 2}
ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII']
IGNORE = {'small', 'footnotesize', 'scriptsize', 'tiny', 'sffamily', 'bfseries', 'normalfont', 'centering',
          'noindent', 'smallskip', 'medskip', 'bigskip', 'hfill', 'par', 'raggedright', 'itshape',
          'columnbreak', 'large', 'normalsize', 'displaystyle', 'big', 'Big'}


def esc_math(s):
    s = re.sub(r'\\color\{[^}]*\}', '', s)
    return esc(s)


def plain(s):
    """Titre TeX → texte simple (sommaire)."""
    t = re.sub(r'\$([^$]*)\$', lambda m: re.sub('<[^>]+>', '', tex_svg(m.group(1))).replace('&amp;', '&'), s)
    return t.replace('--', '–').replace('&lt;', '<').replace('&gt;', '>').strip()


class Conv:
    def __init__(self, chapitre):
        self.chapitre = chapitre
        self.sections = []
        self.hero_notes = []
        self.cnt = {'activite': 0, 'application': 0}
        self.objectifs = None
        self.meta = None
        self.sub = 0

    # ---- texte
    def inline(self, s):
        out, i, n = [], 0, len(s)
        while i < n:
            c = s[i]
            if c == '$':
                j = i + 1
                while j < n and s[j] != '$':
                    j += 2 if s[j] == '\\' else 1
                out.append('\\(' + esc_math(s[i + 1:j]) + '\\)')
                i = j + 1
            elif c == '\\':
                m = re.match(r'\\([A-Za-z]+)\*?|\\(.)', s[i:], re.S)
                if not m:
                    i += 1
                    continue
                j = i + m.end()
                name = m.group(1)
                if name:
                    if name in ('textbf', 'textit', 'emph', 'textsuperscript', 'text', 'mbox', 'underline', 'blanc'):
                        while s[j] == ' ':
                            j += 1
                        a, j = group(s, j)
                        tag = {'textbf': 'strong', 'textit': 'em', 'emph': 'em', 'textsuperscript': 'sup',
                               'underline': 'u'}.get(name)
                        out.append('<%s>%s</%s>' % (tag, self.inline(a), tag) if tag else self.inline(a))
                    elif name == 'color':
                        _, j = group(s, j)
                    elif name == 'fcolorbox':
                        _, j = group(s, j)
                        _, j = group(s, j)
                        a, j = group(s, j)
                        out.append('<span class="encadre">%s</span>' % self.inline(a))
                    elif name in ('vspace', 'hspace'):
                        if s[j] == '*':
                            j += 1
                        _, j = group(s, j)
                    elif name in IGNORE:
                        out.append(' ')
                    elif name in ('quad', 'qquad'):
                        out.append(' ')
                    elif name in ('dots', 'ldots'):
                        out.append('…')
                    elif name == 'newline':
                        out.append('<br>')
                    elif name == 'renewcommand':
                        _, j = group(s, j)
                        _, j = group(s, j)
                    else:
                        WARN.append('commande texte ignorée : \\' + name)
                else:
                    ch = m.group(2)
                    if ch == '\\':
                        _, j = optarg(s, j)
                        out.append('<br>')
                    elif ch in ' ,;:!':
                        out.append(' ')
                    elif ch in '{}%&$_#':
                        out.append(esc(ch))
                i = j
            elif c == '{':
                a, j = group(s, i)
                out.append(self.inline(a))
                i = j
            elif c == '}':
                i += 1
            elif c == '~':
                out.append('\u00a0')
                i += 1
            elif s.startswith('--', i):
                out.append('–')
                i += 2
            else:
                out.append(esc(c))
                i += 1
        t = re.sub(r'\s+', ' ', ''.join(out))
        t = re.sub(r'(\s*<br>\s*)+$', '', t)
        t = re.sub(r'^(\s*<br>\s*)+', '', t)
        return t.strip()

    def paras(self, s, li=False):
        out = []
        for p in re.split(r'\n\s*\n', s):
            t = self.inline(p)
            if t:
                out.append(t if li else '<p>%s</p>' % t)
        return ('<br>'.join(out)) if li else '\n'.join(out)

    # ---- figures
    def figure(self, opt, body, caption=''):
        svg = render_tikz(opt, body)
        if svg is None:
            return ''
        if svg == 'MATH':
            svg = ('\\[x\\ \\xrightarrow{\\ f\\ }\\ f(x)\\ \\xrightarrow{\\ g\\ }\\ g\\big(f(x)\\big)\\]'
                   '<figcaption>\\(g\\circ f\\) : on applique \\(f\\), puis \\(g\\).</figcaption>')
            return '<figure class="fig">%s</figure>' % svg
        cls = 'fig tabvar' if '\\tkzTabInit' in body else 'fig'
        cap = '<figcaption>%s</figcaption>' % caption if caption else ''
        return '<figure class="%s">%s%s</figure>' % (cls, svg, cap)

    def fig_minipage(self, inner):
        """Minipage contenant une figure : figure + légende (texte restant)."""
        m = re.search(r'\\begin\{tikzpicture\}', inner)
        o, j = optarg(inner, m.end())
        e0, e1 = env_end(inner, j, 'tikzpicture')
        rest = inner[:m.start()] + inner[e1:]
        rest = re.sub(r'\\centering', '', rest)
        return self.figure(o, inner[j:e0], self.inline(rest))

    def is_fig(self, inner):
        if '\\begin{tikzpicture}' not in inner:
            return False
        rest = re.sub(r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}', '', inner, flags=re.S)
        return inner.count('\\begin{tikzpicture}') == 1 and len(re.sub(r'\\[A-Za-z]+|[{}\s]', '', rest)) < 160

    # ---- contenu de bloc
    def content(self, s, li=False):
        parts, buf, i = [], '', 0
        pat = re.compile(r'\\begin\{([\w*]+)\}|(?<!\\)\\\[')
        while True:
            m = pat.search(s, i)
            while m and len(re.findall(r'(?<!\\)\$', s[:m.start()])) % 2:
                m = pat.search(s, m.end())
            if not m:
                buf += s[i:]
                break
            buf += s[i:m.start()]
            if buf.strip():
                parts.append(self.paras(buf, li))
            buf = ''
            if m.group(0) == '\\[':
                e = s.index('\\]', m.end())
                parts.append('\\[' + esc_math(s[m.end():e]) + '\\]')
                i = e + 2
                continue
            name = m.group(1)
            j = m.end()
            opt, j = optarg(s, j)
            args = []
            for _ in range(ARGS.get(name, 0)):
                while s[j] in ' \n':
                    j += 1
                a, j = group(s, j)
                args.append(a)
            e0, e1 = env_end(s, j, name)
            inner = s[j:e0]
            i = e1
            if name in ('itemize', 'enumerate'):
                parts.append(self.liste(name, opt, inner))
            elif name in ('center', 'multicols'):
                parts.append(self.content(inner, li))
            elif name in ('tabular', 'tabularx'):
                parts.append(self.table(inner))
            elif name in ('gather*', 'gather'):
                parts.append('\\[\\begin{gathered}' + esc_math(inner) + '\\end{gathered}\\]')
            elif name in ('align*', 'align'):
                parts.append('\\[\\begin{aligned}' + esc_math(inner) + '\\end{aligned}\\]')
            elif name == 'tikzpicture':
                parts.append(self.figure(opt, inner))
            elif name == 'minipage':
                mps = [inner]
                while True:
                    mm = re.match(r'\s*(\\hfill)?\s*\\begin\{minipage\}', s[i:])
                    if not mm:
                        break
                    k = i + mm.end()
                    _, k = optarg(s, k)
                    _, k = group(s, k)
                    f0, f1 = env_end(s, k, 'minipage')
                    mps.append(s[k:f0])
                    i = f1
                figs = [mp for mp in mps if self.is_fig(mp)]
                texts = [mp for mp in mps if not self.is_fig(mp)]
                if not texts and len(figs) > 1:
                    texts = [mp for mp in figs if '\\tkzTabInit' in mp][:1] or figs[:1]
                    figs = [mp for mp in figs if mp not in texts]
                if figs and texts:
                    fig_html = ''.join(self.fig_minipage(f) for f in figs)
                    txt_html = ''.join(self.content(t) for t in texts)
                    if fig_html:
                        parts.append('<div class="avec-fig">\n<div>\n%s\n</div>\n%s\n</div>' % (txt_html, fig_html))
                    else:
                        parts.append(txt_html)
                else:
                    for mp in mps:
                        parts.append(self.fig_minipage(mp) if self.is_fig(mp) else self.content(mp))
            else:
                WARN.append('environnement ignoré : ' + name)
        if buf.strip():
            parts.append(self.paras(buf, li))
        return '\n'.join(p for p in parts if p)

    def liste(self, name, opt, inner):
        d, starts = 0, []
        for m in re.finditer(r'\\begin\{|\\end\{|\\item\b', inner):
            t = m.group(0)
            if t == '\\begin{':
                d += 1
            elif t == '\\end{':
                d -= 1
            elif d == 0:
                starts.append(m)
        lis = []
        for k, m in enumerate(starts):
            end = starts[k + 1].start() if k + 1 < len(starts) else len(inner)
            item = inner[m.end():end]
            bloc = re.search(r'\\begin\{(tabular|tabularx|tikzpicture|minipage)\}', item)
            lis.append('  <li>%s</li>' % self.content(item, li=not bloc))
        tag = 'ul' if name == 'itemize' else 'ol'
        cls = ' class="alpha"' if opt and '\\alph' in opt else ''
        return '<%s%s>\n%s\n</%s>' % (tag, cls, '\n'.join(lis), tag)

    def table(self, inner):
        inner = re.sub(r'\\renewcommand\{\\arraystretch\}\{[^}]*\}', '', inner)
        rows = [re.sub(r'^\s*\[[^\]]*\]', '', re.sub(r'\\hline|\\cline\{[^}]*\}', '', r)).strip()
                for r in split_top(inner, '\\\\')]
        rows = [r for r in rows if r]
        def tikz_row(r):
            cs = split_top(r, '&')
            return all('\\begin{tikzpicture}' in c for c in cs)
        if len(rows) == 2 and not tikz_row(rows[0]) and tikz_row(rows[1]):
            rows = [rows[1], rows[0]]   # légendes au-dessus des figures
        if '\\begin{tikzpicture}' in inner and tikz_row(rows[0]) and (len(rows) == 1 or (len(rows) == 2 and '\\begin{tikzpicture}' not in rows[1])):
            figs = [c for c in split_top(rows[0], '&')]
            caps = split_top(rows[1], '&') if len(rows) > 1 else [''] * len(figs)
            items = []
            for f, c in zip(figs, caps):
                m = re.search(r'\\begin\{tikzpicture\}', f)
                o, j = optarg(f, m.end())
                e0, _ = env_end(f, j, 'tikzpicture')
                items.append(self.figure(o, f[j:e0], self.inline(c)))
            return '<div class="figs" style="--n:%d">%s</div>' % (len(items), ''.join(items))
        head, body = [], []
        for r in rows:
            r = r.strip()
            if r.startswith('\\entete'):
                cells = split_top(r[len('\\entete'):], '&')
                head.append('<tr>%s</tr>' % ''.join('<th scope="col">%s</th>' % self.inline(c) for c in cells))
            else:
                cells = split_top(r, '&')
                body.append('<tr>%s</tr>' % ''.join('<td>%s</td>' % self.content(c, li=True) for c in cells))
        t = '<div class="tableau"><table>'
        if head:
            t += '<thead>%s</thead>' % ''.join(head)
        return t + '<tbody>%s</tbody></table></div>' % ''.join(body)

    def bloc(self, name, opt, inner):
        title = None
        if opt and 'title=' in opt:
            k = opt.index('title=') + 6
            title, _ = group(opt, k) if opt[k] == '{' else (opt[k:].split(',')[0], 0)
        if name in self.cnt:
            self.cnt[name] += 1
        if title is None:
            title = {'activite': 'Activité %d', 'application': 'Application %d'}.get(
                name, TAG.get(name, '')) % ((self.cnt[name],) if name in self.cnt else ())
        title = title.replace(' -- ', ' — ')
        return '  <div class="bloc %s"><div class="tag">%s</div>\n%s\n  </div>' % (
            BLOCS[name], self.inline(title), self.content(inner))

    # ---- niveau document
    def add(self, html):
        if not self.sections:
            self.hero_notes.append(html)
        else:
            self.sections[-1]['body'].append(html)

    def run(self, body):
        i = 0
        rx = re.compile(r'\\(EnteteCours|Partie|SousPartie|Needspace\*?|begin)(?![A-Za-z])')
        while i < len(body):
            m = rx.search(body, i)
            text = body[i:m.start() if m else len(body)]
            if text.strip() and self.inline(text):
                self.add(self.paras(text))
            if not m:
                break
            kind, j = m.group(1), m.end()
            if kind == 'EnteteCours':
                a1, j = group(body, j)
                a2, j = group(body, j)
                a3, j = group(body, j)
                self.meta = (a1, a2, a3)
            elif kind == 'Partie':
                t, j = group(body, j)
                n = len(self.sections)
                self.sections.append({'num': ROMAN[n], 'title': t, 'body': []})
                self.sub = 0
            elif kind == 'SousPartie':
                t, j = group(body, j)
                self.sub += 1
                self.add('  <h3><span class="n">%s.%d</span>%s</h3>' % (self.sections[-1]['num'], self.sub, self.inline(t)))
            elif kind.startswith('Needspace'):
                _, j = group(body, j)
            else:
                name, j = group(body, j)
                opt, j = optarg(body, j)
                e0, e1 = env_end(body, j, name)
                inner = body[j:e0]
                j = e1
                if name == 'objectifs':
                    lists = []
                    for mm in re.finditer(r'\\begin\{itemize\}', inner):
                        _, k = optarg(inner, mm.end())
                        f0, _ = env_end(inner, k, 'itemize')
                        lists.append(self.liste('itemize', None, inner[k:f0]))
                    self.objectifs = lists
                elif name == 'tcolorbox':
                    title = ''
                    if opt and 'title=' in opt:
                        k = opt.index('title=') + 6
                        title = '<strong>%s</strong> ' % self.inline(group(opt, k)[0] if opt[k] == '{' else opt[k:].split(',')[0])
                    self.add('<div class="cadre">%s%s</div>' % (title, self.inline(inner)))
                elif name in BLOCS:
                    self.add(self.bloc(name, opt, inner))
                else:
                    self.add(self.content(body[m.start():j]))
            i = j

    def html(self, semestre):
        titre, lecon, duree = self.meta
        notes = '\n'.join('  ' + n for n in self.hero_notes)
        obj = ''
        if self.objectifs:
            obj = ('  <div class="cadre objectif"><strong>Contenus</strong>\n%s\n  </div>\n'
                   '  <div class="cadre objectif"><strong>Capacités attendues</strong>\n%s\n  </div>') % tuple(self.objectifs[:2])
        hero = '''<div class="hero">
  <div class="hero-card">
    <div>
      <div class="chips">
        <span class="chip">%s</span>
        <span class="chip or">Chapitre %s</span>
        <span class="chip">%s</span>
      </div>
      <h1 id="cours-titre">%s</h1>
      <p class="sous-titre">Volume horaire : %s</p>
      <div class="auteur">Elhadi Abdelmounaim</div>
    </div>
    <div class="stats" data-stats></div>
  </div>
%s
%s
</div>''' % (esc(NIVEAU), self.chapitre, esc(semestre), self.inline(titre), esc(HEURES or duree), obj, notes)
        secs = []
        for k, sct in enumerate(self.sections, 1):
            secs.append('''<!-- ============================ %s ============================ -->
<section class="chap" id="s%d" data-toc="%s">
  <h2><span class="num">%s</span><span class="titre">%s</span></h2>
%s
</section>''' % (sct['num'], k, esc(plain(sct['title'])).replace('"', '&quot;'), sct['num'],
                 self.inline(sct['title']), '\n'.join(sct['body'])))
        return hero, '\n\n'.join(secs)


NIVEAU, DOSSIER, HEURES = '1ère année Bac Sciences', '1BAC_SE', ''

TEMPLATE = '''{%% extends "education/cours/_base.html" %%}
{%% comment %%}
Cours en ligne : %s — %s (chapitre %s, %s).
Généré depuis %s (le PDF d'origine est dans le dossier Cours de la leçon, media/lessons/%s/).
Le contenu est entre « verbatim » : les accolades du LaTeX ne sont pas interprétées par Django.
Dans les formules, « < », « > » et « & » sont écrits &lt;, &gt; et &amp;.
{%% endcomment %%}

{%% block hero %%}{%% verbatim %%}
%s
{%% endverbatim %%}{%% endblock %%}

{%% block cours %%}{%% verbatim %%}
%s
{%% endverbatim %%}{%% endblock %%}
'''


def inter_tikz(m):
    """\\inter{a}{b}{ta}{tb}{la}{lb} (L'ordre dans R) : intervalle sur la droite numérique."""
    a, b, ta, tb, la, lb = m.groups()
    k = 0.42
    xa, xb, d = float(a) * k, float(b) * k, 0.45 * k
    out = ['\\draw[gris,-{Stealth}] (%.3f,0) -- (%.3f,0);' % (-4 * k, 4 * k),
           '\\draw[line width=2.2pt,niveau] (%.3f,0) -- (%.3f,0);' % (xa, xb)]
    for x, t, sens in ((xa, ta, 1), (xb, tb, -1)):
        if t == 'n':
            continue
        e = x + d * sens * (1 if t == 'c' else -1)
        out.append('\\draw[niveau,very thick] (%.3f,0.2) -- (%.3f,0.2) -- (%.3f,-0.2) -- (%.3f,-0.2);' % (e, x, x, e))
    for x, t, l in ((xa, ta, la), (xb, tb, lb)):
        if t != 'n':
            out.append('\\node[font=\\scriptsize,below] at (%.3f,-0.2) {$%s$};' % (x, l))
    return '\\begin{tikzpicture}' + ' '.join(out) + '\\end{tikzpicture}'


def convert(path, chapitre, out):
    src = open(path, encoding='utf-8').read()
    src = re.sub(r'(?<!\\)%.*', '', src)
    pre, _, rest = src.partition('\\begin{document}')
    body = rest.partition('\\end{document}')[0]
    cube = re.search(r'\\newcommand\{\\cube\}\[1\]\[([\d.]+)\]\{%?', pre)
    if cube:
        cb, _ = group(pre, cube.end() - 1)
        body = re.sub(r'\\cube(?![A-Za-z])(\[([\d.]+)\])?', lambda m: cb.replace('#1', m.group(2) or cube.group(1)), body)
    body = re.sub(r'\\inter' + r'\{([^{}]*)\}' * 6, inter_tikz, body)
    body = expand(body, macros_du_preambule(pre))
    sem = re.search(r'\\newcommand\{\\Semestre\}\{([^}]*)\}', pre).group(1)
    c = Conv(chapitre)
    c.run(body)
    hero, cours = c.html(sem)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(TEMPLATE % (NIVEAU, c.meta[0], chapitre, c.meta[2], path.split('/')[-1], DOSSIER, hero, cours))
    return c


if __name__ == '__main__':
    if len(sys.argv) > 4:
        NIVEAU, DOSSIER = sys.argv[4], sys.argv[5]
        HEURES = sys.argv[6] if len(sys.argv) > 6 else ''
    convert(sys.argv[1], sys.argv[2], sys.argv[3])
    for w in sorted(set(WARN)):
        print('!', w)
