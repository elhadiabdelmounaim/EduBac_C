"""Contexte du programme marocain de mathématiques (lycée)."""
LEVELS = {
    'tronc_commun': 'Tronc commun scientifique',
    'tronc_commun_lettres': 'Tronc commun lettres',
    '1bac_sm': '1re année du Bac — Sciences mathématiques',
    '1bac_se': '1re année du Bac — Sciences expérimentales',
    '1bac_lettres': '1re année du Bac — Lettres',
    '2bac_sm': '2e année du Bac — Sciences mathématiques',
    '2bac_pc': '2e année du Bac — Sciences physiques',
    '2bac_svt': '2e année du Bac — Sciences de la vie et de la Terre',
    '2bac_se': '2e année du Bac — Sciences expérimentales',
}


def level_label(code):
    return LEVELS.get(code or '', code or 'niveau non précisé')
