"""Cahier de textes en PDF (reportlab) : une séance, une sélection ou tout un niveau.

Les polices DejaVu (cahier/fonts) affichent les accents et les symboles des titres (π, √, ≤…)."""
import datetime
import io
from pathlib import Path
from xml.sax.saxutils import escape

from django.utils import dateformat
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, HRFlowable, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

POLICES = Path(__file__).resolve().parent / 'fonts'
MARINE = colors.HexColor('#12306b')
ORANGE = colors.HexColor('#f39c12')
GRIS = colors.HexColor('#56627a')
TRAIT = colors.HexColor('#d9e0ec')
FOND = colors.HexColor('#f4f7fb')


def _polices():
    if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('DejaVu', str(POLICES / 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', str(POLICES / 'DejaVuSans-Bold.ttf')))
        pdfmetrics.registerFontFamily('DejaVu', normal='DejaVu', bold='DejaVu-Bold',
                                      italic='DejaVu', boldItalic='DejaVu-Bold')


def _styles():
    base = ParagraphStyle('base', fontName='DejaVu', fontSize=10, leading=14, textColor=colors.HexColor('#1f2937'))
    return {
        'base': base,
        'petit': ParagraphStyle('petit', parent=base, fontSize=8.5, leading=11, textColor=GRIS),
        'bandeau': ParagraphStyle('bandeau', parent=base, fontName='DejaVu-Bold', fontSize=11.5, leading=15,
                                  textColor=colors.white),
        'bandeau_droite': ParagraphStyle('bd', parent=base, fontSize=9.5, leading=13, textColor=colors.white,
                                         alignment=2),
        'rubrique': ParagraphStyle('rubrique', parent=base, fontName='DejaVu-Bold', fontSize=10, leading=14,
                                   textColor=MARINE, spaceBefore=6, spaceAfter=2),
        'partie': ParagraphStyle('partie', parent=base, fontName='DejaVu-Bold', leftIndent=6, spaceBefore=3),
        'sous_titre': ParagraphStyle('st', parent=base, leftIndent=16, textColor=colors.HexColor('#1d4fa3')),
        'element': ParagraphStyle('el', parent=base, leftIndent=30, bulletIndent=20),
        'titre': ParagraphStyle('titre', parent=base, fontName='DejaVu-Bold', fontSize=26, leading=32,
                                textColor=MARINE, alignment=TA_CENTER),
        'sous_titre_couv': ParagraphStyle('stc', parent=base, fontSize=15, leading=20, alignment=TA_CENTER,
                                          textColor=GRIS),
        'h2': ParagraphStyle('h2', parent=base, fontName='DejaVu-Bold', fontSize=15, leading=20,
                             textColor=MARINE, spaceAfter=8),
    }


def date_longue(d, majuscule=True):
    texte = dateformat.format(d, 'l j F Y')
    return texte[:1].upper() + texte[1:] if majuscule else texte


def _e(texte):
    return escape(str(texte or ''))


def _bloc(s, st, avec_enseignant):
    """Une séance : bandeau (numéro, leçon, date), informations, contenu, activités, observations."""
    titre = 'Séance n° %s — %s' % (s.numero, _e(s.lesson.title)) if getattr(s, 'numero', None) else _e(s.lesson.title)
    bandeau = Table([[Paragraph(titre, st['bandeau']), Paragraph(_e(date_longue(s.date)), st['bandeau_droite'])]],
                    colWidths=['68%', '32%'])
    bandeau.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), MARINE), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -1), 2, ORANGE),
    ]))
    infos = ['<b>Classe :</b> %s' % _e(s.classroom.name), '<b>Niveau :</b> %s' % _e(s.lesson.course.get_niveau_display())]
    if avec_enseignant:
        infos.append('<b>Enseignant :</b> %s' % _e(s.teacher.get_full_name() or s.teacher.username))
    if getattr(s, 'minutes_texte', None) and s.minutes:
        infos.append('<b>Durée réalisée :</b> %s' % _e(s.minutes_texte))
    tete = [bandeau, Spacer(1, 4), Paragraph(' · '.join(infos), st['base']),
            Paragraph('Contenu pédagogique réalisé', st['rubrique'])]
    corps = []
    for partie in s.parties:
        corps.append(Paragraph(_e(partie['titre']), st['partie']))
        for g in partie['groupes']:
            if g['titre']:
                corps.append(Paragraph(_e(g['titre']), st['sous_titre']))
            for e in g['elements']:
                corps.append(Paragraph(_e(e), st['element'], bulletText='•'))
    if not corps:
        corps.append(Paragraph('—', st['base']))
    fin = []
    if s.activites:
        fin.append(Paragraph('Activités et exercices effectués', st['rubrique']))
        fin.append(Paragraph(_e(' ; '.join(s.activites)), st['base']))
    fin.append(Paragraph('Observations', st['rubrique']))
    fin.append(Paragraph(_e(s.observations).replace('\n', '<br/>') if s.observations.strip() else '—', st['base']))
    # Le bandeau ne reste jamais seul en bas de page.
    return [CondPageBreak(45 * mm), KeepTogether(tete + corps[:2])] + corps[2:] + fin


def document(seances, niveau, couverture=False, avec_enseignant=False, titre_fichier='Cahier de textes'):
    """seances : déjà préparées (numero, parties, activites, minutes_texte), dans l'ordre chronologique."""
    _polices()
    st = _styles()
    tampon = io.BytesIO()
    genere = date_longue(datetime.date.today(), majuscule=False)

    def decor(canvas, doc):
        canvas.saveState()
        largeur, hauteur = A4
        canvas.setFillColor(MARINE)
        canvas.setFont('DejaVu-Bold', 10)
        canvas.drawString(18 * mm, hauteur - 12 * mm, 'EduBac')
        canvas.setFillColor(GRIS)
        canvas.setFont('DejaVu', 8.5)
        canvas.drawString(33 * mm, hauteur - 12 * mm, '· Cahier de textes · %s' % niveau)
        canvas.setStrokeColor(ORANGE)
        canvas.setLineWidth(1)
        canvas.line(18 * mm, hauteur - 14 * mm, largeur - 18 * mm, hauteur - 14 * mm)
        canvas.drawString(18 * mm, 10 * mm, 'Généré le %s' % genere)
        canvas.drawRightString(largeur - 18 * mm, 10 * mm, 'Page %d' % doc.page)
        canvas.restoreState()

    doc = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=20 * mm, bottomMargin=18 * mm, title=titre_fichier, author='EduBac')
    histoire = []
    if couverture:
        debut, fin = seances[0].date, seances[-1].date
        histoire += [Spacer(1, 55 * mm), Paragraph('Cahier de textes', st['titre']), Spacer(1, 6 * mm),
                     Paragraph(_e(niveau), st['sous_titre_couv']), Spacer(1, 14 * mm),
                     Paragraph('Période : du %s au %s' % (_e(date_longue(debut, False)), _e(date_longue(fin, False))),
                               st['sous_titre_couv']),
                     Spacer(1, 4 * mm),
                     Paragraph('%d séance%s' % (len(seances), 's' if len(seances) > 1 else ''), st['sous_titre_couv']),
                     Spacer(1, 30 * mm), Paragraph('EduBac — plateforme de mathématiques', st['petit']),
                     PageBreak(), Paragraph('Sommaire', st['h2'])]
        lignes = [['N°', 'Date', 'Classe', 'Leçon']]
        for s in seances:
            lignes.append([str(getattr(s, 'numero', '') or ''), s.date.strftime('%d/%m/%Y'),
                           Paragraph(_e(s.classroom.name), st['petit']), Paragraph(_e(s.lesson.title), st['petit'])])
        sommaire = Table(lignes, colWidths=[14 * mm, 24 * mm, 45 * mm, None], repeatRows=1)
        sommaire.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, 0), 'DejaVu-Bold', 9), ('FONT', (0, 1), (-1, -1), 'DejaVu', 8.5),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('BACKGROUND', (0, 0), (-1, 0), MARINE),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, FOND]),
            ('GRID', (0, 0), (-1, -1), 0.4, TRAIT), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        histoire += [sommaire, PageBreak()]
    for k, s in enumerate(seances):
        if k:
            histoire += [Spacer(1, 4 * mm), HRFlowable(width='100%', thickness=1.2, color=ORANGE, dash=(3, 2)),
                         Spacer(1, 5 * mm)]
        histoire += _bloc(s, st, avec_enseignant)
    doc.build(histoire, onFirstPage=decor, onLaterPages=decor)
    return tampon.getvalue()
