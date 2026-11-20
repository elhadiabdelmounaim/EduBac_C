"""Tests du service IA (fournisseur « mock », sans réseau)."""
import os
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient

    from ai_service import providers
    from ai_service.app import app
except ImportError:  # dépendances du service IA absentes sur cette machine
    raise unittest.SkipTest('Service IA : pip install -r ai_service/requirements.txt')

HEADERS = {'X-Service-Token': 'secret-test'}


@mock.patch.dict(os.environ, {'AI_SERVICE_TOKEN': 'secret-test', 'AI_PROVIDERS': 'mock'})
class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_token_is_required(self):
        self.assertEqual(self.client.post('/v1/solve', json={'question': 'x'}).status_code, 401)
        self.assertEqual(self.client.post('/v1/solve', json={'question': 'x'},
                                          headers={'X-Service-Token': 'faux'}).status_code, 401)

    def test_solve_includes_exact_sympy_result(self):
        r = self.client.post('/v1/solve', json={'latex': 'x^{2}-4=0', 'level': '1bac_sm'}, headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        blocks = r.json()['blocks']
        self.assertEqual(blocks[0]['content'], 'Résultat exact (SymPy) :')
        self.assertIn('-2; 2', blocks[1]['content'])
        self.assertEqual(r.json()['provider'], 'mock')

    def test_verify_uses_sympy_verdict(self):
        ok = self.client.post('/v1/verify', json={'student_answer': '(x+1)^{2}', 'expected': 'x^2+2x+1'},
                              headers=HEADERS).json()
        self.assertEqual(ok['verification'], {'correct': True, 'method': 'sympy', 'details': 'Avis du modèle.'})
        wrong = self.client.post('/v1/verify', json={'student_answer': 'x^2+1', 'expected': '(x+1)^2'},
                                 headers=HEADERS).json()
        self.assertFalse(wrong['verification']['correct'])

    def test_exercises_hide_answers_from_students(self):
        teacher = self.client.post('/v1/exercises', json={'role': 'teacher', 'chapter': 'Polynômes'},
                                   headers=HEADERS).json()
        student = self.client.post('/v1/exercises', json={'role': 'student'}, headers=HEADERS).json()
        self.assertIn('Réponse :', [b['content'] for b in teacher['blocks']])
        self.assertNotIn('Réponse :', [b['content'] for b in student['blocks']])

    def test_all_endpoints_and_validation(self):
        for action in ('analyze', 'explain', 'hint'):
            self.assertEqual(self.client.post(f'/v1/{action}', json={'question': 'Limite de 1/x ?'},
                                              headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.post('/v1/hint', json={}, headers=HEADERS).status_code, 400)
        self.assertEqual(self.client.post('/v1/hint', json={'question': 'x' * 5000},
                                          headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})

    def test_dangerous_latex_from_model_becomes_text(self):
        evil = mock.Mock()
        evil.name = 'evil'
        evil.complete.return_value = '{"reply": "x", "blocks": [{"type": "math", "content": "\\\\href{javascript:1}{x}"}]}'
        with mock.patch.object(providers, 'configured_providers', return_value=[evil]):
            r = self.client.post('/v1/explain', json={'question': 'q'}, headers=HEADERS).json()
        self.assertEqual(r['blocks'][0]['type'], 'text')

    def test_provider_fallback_and_total_failure(self):
        broken = mock.Mock()
        broken.name = 'broken'
        broken.complete.side_effect = providers.ProviderError('panne')
        with mock.patch.object(providers, 'configured_providers', return_value=[broken, providers.MockProvider()]):
            r = self.client.post('/v1/explain', json={'question': 'q'}, headers=HEADERS)
        self.assertEqual(r.json()['provider'], 'mock')
        with mock.patch.object(providers, 'configured_providers', return_value=[broken]):
            r = self.client.post('/v1/explain', json={'question': 'q'}, headers=HEADERS)
        self.assertEqual(r.status_code, 503)


class ProviderConfigTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {'AI_PROVIDERS': 'groq,openrouter,inconnu', 'GROQ_API_KEY': 'k'}, clear=True)
    def test_only_configured_providers_are_used(self):
        names = [p.name for p in providers.configured_providers()]
        self.assertEqual(names, ['groq'])


if __name__ == '__main__':
    unittest.main()
