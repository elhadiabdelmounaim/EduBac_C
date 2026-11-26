"""Filtre de gabarit : la leçon est-elle encore verrouillée pour le lecteur de la page ?
Usage : {% load acces_lecons %} … {% if lesson|verrouillee:request %}🔒{% endif %}"""
from django import template

register = template.Library()


@register.filter
def verrouillee(lesson, request):
    from cahier.acces import peut_voir
    return not peut_voir(request, lesson)
