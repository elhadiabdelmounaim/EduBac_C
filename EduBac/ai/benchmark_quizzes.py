"""Opt-in live measurements on synthetic fixtures in an isolated SQLite test DB.

cd EduBac && DJANGO_SETTINGS_MODULE=browser_tests.settings \
python -m ai.benchmark_quizzes --live --output /tmp/quiz-benchmark.json

Consumes the configured provider quota; never uses the application's users or quizzes.
"""
import argparse
import json
import time
import unittest
from pathlib import Path

CASES = [
    ("tronc_commun", "Équations du premier degré", 1,
     "Un problème de budget pour des cahiers avec frais fixes et prix unitaire. Données simples et suffisantes.", True),
    ("1ere_bac_sm", "Dérivation", 2,
     "Deux situations distinctes : interprétation géométrique d’une dérivée et détermination d’une tangente "
     "pour une fonction polynomiale. Ne pas produire des variantes numériques.", False),
    ("2eme_bac_svt", "Suites numériques", 4,
     "Quatre compétences distinctes : reconnaître une suite géométrique, exploiter une récurrence, "
     "étudier la monotonie, calculer une somme de termes. Situations et raisonnements différents.", False),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize real, paid/quota-limited API calls.")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("Real provider calls require --live.")
    import django
    from django.conf import settings
    if settings.SETTINGS_MODULE != "browser_tests.settings":
        parser.error("Use DJANGO_SETTINGS_MODULE=browser_tests.settings for isolated fixtures.")
    django.setup()
    from django.test import TestCase
    from django.test.runner import DiscoverRunner
    from django.test.utils import CaptureQueriesContext
    from django.db import connection
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse
    from accounts.models import User
    from education.models import Course, Lesson
    from quizzes.models import Quiz, QuizGenerationRun
    records = []
    output = Path(args.output)

    class LiveBenchmark(TestCase):
        def runTest(self):
            teacher = User.objects.create_user(
                username="performance-fixture", email="perf@example.test", role="teacher",
            )
            session = self.client.session
            session["user_id"] = teacher.pk
            session.save()
            for level, title, count, description, source in CASES:
                lesson = Lesson.objects.create(
                    course=Course.objects.create(name="Mathématiques", niveau=level), title=title,
                )
                body = {
                    "action": "generate", "lesson": lesson.pk, "niveau": level,
                    "question_count": count, "difficulty": "moyen", "description": description,
                    "resource_selection_present": "1",
                    "generation_mode": "resources" if source else "topic",
                }
                if source:
                    body["resource_uploads"] = [SimpleUploadedFile(
                        "Méthode.txt", "Équations du premier degré : isoler l’inconnue puis vérifier.\n"
                        "Exemple : Résoudre $2x+3=11$.\nRésolution : $x=4$.".encode(),
                    )]
                started = time.perf_counter()
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.post(reverse("quizzes:teacher_ai"), body)
                run = QuizGenerationRun.objects.filter(owner=teacher).latest("created_at")
                record = {
                    "level": level, "count": count, "total_s": time.perf_counter() - started,
                    "success": response.context["error"] is None,
                    "error": response.context["error"], "sql_count": len(queries),
                    "sql_s": sum(float(query["time"]) for query in queries), "metrics": run.metrics,
                }
                quiz = Quiz.objects.filter(lesson=lesson).first()
                if quiz:
                    record["questions"] = list(quiz.questions.values("text", "correct_answer", "explanation"))
                records.append(record)
                output.write_text(json.dumps(records, ensure_ascii=False, indent=2))
                print(json.dumps(record, ensure_ascii=False), flush=True)

    runner = DiscoverRunner(verbosity=0, interactive=False)
    runner.setup_test_environment()
    databases = runner.setup_databases()
    try:
        result = unittest.TextTestRunner().run(unittest.TestSuite([LiveBenchmark()]))
        if not result.wasSuccessful():
            raise SystemExit(1)
    finally:
        runner.teardown_databases(databases)
        runner.teardown_test_environment()


if __name__ == "__main__":
    main()
