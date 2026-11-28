"""Sondages rapides du salon de classe : création (professeur), vote (un choix par personne,
modifiable tant que le sondage est ouvert), résumé pour chaque lecteur."""

OPTIONS_MIN, OPTIONS_MAX = 2, 6


class SondageInvalide(ValueError):
    pass


def nettoyer(question, options):
    question = ' '.join(str(question or '').split())[:300]
    options = [' '.join(str(o or '').split())[:120] for o in (options or [])]
    options = [o for o in options if o]
    if not question:
        raise SondageInvalide('Écrivez la question du sondage.')
    if len(options) < OPTIONS_MIN:
        raise SondageInvalide(f'Il faut au moins {OPTIONS_MIN} choix.')
    if len(options) > OPTIONS_MAX:
        raise SondageInvalide(f'{OPTIONS_MAX} choix au plus.')
    if len({o.lower() for o in options}) != len(options):
        raise SondageInvalide('Deux choix sont identiques.')
    return question, options


def resume_sondage(message, user):
    """{id, question, options:[{text, count, percent, mine, names?}], total, closed, can_close} ou None.
    Les noms des votants ne sont visibles que du professeur (comme pour les réactions)."""
    from .models import ChatPoll
    try:
        poll = message.poll
    except ChatPoll.DoesNotExist:
        return None
    if poll is None:
        return None
    votes = list(poll.votes.all())
    total = len(votes)
    user_id = getattr(user, 'pk', None)
    noms = getattr(message, '_reaction_noms', False)
    options = []
    for i, texte in enumerate(poll.options):
        choix = [v for v in votes if v.option == i]
        item = {
            'index': i, 'text': texte, 'count': len(choix),
            'percent': round(100 * len(choix) / total) if total else 0,
            'mine': any(v.user_id == user_id for v in choix),
        }
        if noms:
            item['names'] = [v.user.get_full_name() or v.user.username for v in choix]
        options.append(item)
    return {
        'id': poll.pk, 'question': poll.question, 'options': options, 'total': total,
        'closed': poll.is_closed, 'can_close': noms,
    }
