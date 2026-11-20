"""Fournisseurs d'IA interchangeables.

La plupart des fournisseurs exposent l'API « chat completions » compatible
OpenAI (Groq, OpenRouter, OpenAI, xAI, Gemini, Mistral, serveurs locaux) : une
seule classe suffit, configurée par variables d'environnement.

AI_PROVIDERS=groq,openrouter   → essayés dans cet ordre (repli si erreur)
GROQ_API_KEY, GROQ_MODEL, OPENROUTER_API_KEY, …     (voir README)
AI_PROVIDERS=mock              → réponses de démonstration (tests, développement)
"""
import json
import os

import httpx

DEFAULTS = {
    'groq': ('https://api.groq.com/openai/v1', 'openai/gpt-oss-20b'),
    'openrouter': ('https://openrouter.ai/api/v1', 'openrouter/free'),
    'openai': ('https://api.openai.com/v1', 'gpt-4o-mini'),
    'xai': ('https://api.x.ai/v1', 'grok-3-mini'),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/openai', 'gemini-2.0-flash'),
    'mistral': ('https://api.mistral.ai/v1', 'mistral-small-latest'),
}


class ProviderError(Exception):
    pass


class OpenAICompatibleProvider:
    def __init__(self, name, base_url, api_key, model, timeout=40):
        self.name, self.base_url, self.api_key, self.model, self.timeout = name, base_url.rstrip('/'), api_key, model, timeout

    def complete(self, system, user):
        try:
            response = httpx.post(
                f'{self.base_url}/chat/completions',
                headers={'Authorization': f'Bearer {self.api_key}'},
                json={'model': self.model, 'temperature': 0.2,
                      'response_format': {'type': 'json_object'},
                      'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]},
                timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f'{self.name}: réseau') from exc
        if response.status_code != 200:
            raise ProviderError(f'{self.name}: HTTP {response.status_code}')
        try:
            return response.json()['choices'][0]['message']['content']
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(f'{self.name}: réponse inattendue') from exc


class MockProvider:
    """Réponses déterministes : tests automatiques et démonstration sans clé."""
    name = 'mock'

    def complete(self, system, user):
        task = json.loads(user)
        action = task.get('action')
        if action == 'exercises':
            return json.dumps({'reply': 'Voici un exercice.', 'exercises': [
                {'statement': [{'type': 'text', 'content': 'Résoudre dans ℝ :'},
                               {'type': 'math', 'content': 'x^{2}-5x+6=0'}],
                 'answer': 'S=\\{2;3\\}', 'hint': 'Calculez le discriminant.'}]})
        if action == 'verify':
            return json.dumps({'reply': 'Vérification effectuée.', 'blocks': [
                {'type': 'text', 'content': 'Comparez votre réponse avec le résultat attendu.'}],
                'verification': {'correct': None, 'details': 'Avis du modèle.'}})
        return json.dumps({'reply': f'Réponse ({action}).', 'blocks': [
            {'type': 'text', 'content': 'Étape 1 : identifier la forme de l’expression.'},
            {'type': 'math', 'content': task.get('latex') or 'x'}]})


def configured_providers():
    names = [n.strip().lower() for n in os.getenv('AI_PROVIDERS', 'groq').split(',') if n.strip()]
    providers = []
    for name in names:
        if name == 'mock':
            providers.append(MockProvider())
            continue
        base, model = DEFAULTS.get(name, (None, None))
        base = os.getenv(f'{name.upper()}_BASE_URL', base)
        key = os.getenv(f'{name.upper()}_API_KEY', '')
        model = os.getenv(f'{name.upper()}_MODEL', model)
        if base and key and model:
            providers.append(OpenAICompatibleProvider(name, base, key, model))
    return providers


def complete_json(system, user, providers=None):
    """Premier fournisseur qui répond un JSON valide. Renvoie (données, nom)."""
    providers = configured_providers() if providers is None else providers
    if not providers:
        raise ProviderError('Aucun fournisseur d’IA configuré.')
    errors = []
    for provider in providers:
        try:
            text = provider.complete(system, user)
            start, end = text.find('{'), text.rfind('}')
            return json.loads(text[start:end + 1]), provider.name
        except (ProviderError, ValueError) as exc:
            errors.append(str(exc))
    raise ProviderError('; '.join(errors))
