"""Réactions aux messages : chargement groupé (une requête par liste) et résumé par lecteur."""
from collections import defaultdict

from .models import ChatMessage, ChatReport, DirectMessage, MessageReaction, PrivateMessage

KIND_BY_MODEL = {
    ChatMessage: ChatReport.KIND_CLASS,
    PrivateMessage: ChatReport.KIND_CONSULTATION,
    DirectMessage: ChatReport.KIND_DIRECT,
}


def charger(kind, messages, *, noms=False):
    """Attache à chaque message ses réactions. `noms` : le lecteur voit qui a réagi
    (professeur de la classe ou administration) ; les élèves ne voient que les nombres."""
    messages = [message for message in messages if message is not None]
    par_message = defaultdict(list)
    if messages:
        lignes = (
            MessageReaction.objects
            .filter(kind=kind, message_id__in=[message.pk for message in messages])
            .select_related('user')
            .order_by('created_at', 'pk')
        )
        for ligne in lignes:
            par_message[ligne.message_id].append(ligne)
    for message in messages:
        message._reactions = par_message.get(message.pk, [])
        message._reaction_noms = noms
    return messages


def resume(message, user):
    """[{emoji, label, count, mine, names?}] dans l'ordre de la palette ; vide si supprimé."""
    if message.is_deleted:
        return []
    if getattr(message, '_reactions', None) is None:
        charger(KIND_BY_MODEL[type(message)], [message])
    user_id = getattr(user, 'pk', None)
    groupes = defaultdict(list)
    for ligne in message._reactions:
        groupes[ligne.emoji].append(ligne)
    resultat = []
    for emoji in MessageReaction.EMOJIS:
        lignes = groupes.get(emoji)
        if not lignes:
            continue
        item = {
            'emoji': emoji,
            'label': MessageReaction.LABELS[emoji],
            'count': len(lignes),
            'mine': any(ligne.user_id == user_id for ligne in lignes) if user_id else False,
        }
        if getattr(message, '_reaction_noms', False):
            item['names'] = [ligne.user.get_full_name() or ligne.user.username for ligne in lignes]
        resultat.append(item)
    return resultat
