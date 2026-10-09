"""Verify source files reach the actual AI transport, without paid API calls."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from education.media_library import chapter_relative
from education.models import Course, Lesson
from .services import AIService


@override_settings(QUIZ_SEMANTIC_CHECK_ENABLED=False)
class LessonSourceTransportTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = override_settings(MEDIA_ROOT=self.temp.name)
        settings.enable()
        self.addCleanup(settings.disable)
        course = Course.objects.create(name="Maths", niveau="1ere_bac_sm")
        self.lesson = Lesson.objects.create(
            course=course, title="Logique", order=1, content="Contenu de secours",
        )
        self.folder = Path(self.temp.name) / chapter_relative(self.lesson) / "Sources_IA"
        self.folder.mkdir(parents=True)
        self.source = self.folder / "Règles.txt"
        self.source.write_text("قاعدة : $P \\Rightarrow Q$.", encoding="utf-8")

    @patch.object(AIService, "_get_provider", return_value=SimpleNamespace(
        name="test", model="test",
    ))
    @patch.object(AIService, "_chat")
    def test_generate_quiz_sends_sources_to_provider(self, chat, provider):
        (self.folder / "autre.txt").write_text("SOURCE_NON_CHOISIE", encoding="utf-8")
        chat.return_value = json.dumps({
            "title": "Logique",
            "questions": [{
                "text": "Quelle proposition est vraie ?",
                "choices": [
                    {"text": str(n), "is_correct": n == 0} for n in range(4)
                ],
                "explanation": "Appliquer la règle.",
                "hint": "Relire les propositions.",
            }],
        })
        data = AIService().generate_quiz_from_lesson(
            self.lesson, 1, source_file=self.source.name,
        )
        self.assertEqual(len(data["questions"]), 1)
        prompt = chat.call_args_list[0].args[0][1]["content"]
        self.assertIn("## Source : Règles.txt", prompt)
        self.assertIn("قاعدة : $P \\Rightarrow Q$.", prompt)
        self.assertNotIn("SOURCE_NON_CHOISIE", prompt)
        self.assertNotIn("Contenu de secours", prompt)

    def test_all_sources_and_invalid_selections(self):
        (self.folder / "second.txt").write_text("DEUXIEME_SOURCE", encoding="utf-8")
        context = self.lesson.get_ai_help()["contenu"]
        self.assertIn("Règles.txt", context)
        self.assertIn("DEUXIEME_SOURCE", context)
        for name in ("../Règles.txt", "/tmp/Règles.txt", "missing.txt"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.lesson.get_ai_help(source_file=name)
        self.source.write_text("", encoding="utf-8")
        with self.assertRaisesMessage(ValueError, "vide"):
            self.lesson.get_ai_help(source_file=self.source.name)
        self.source.write_bytes(b"\xff")
        with self.assertRaisesMessage(ValueError, "UTF-8"):
            self.lesson.get_ai_help(source_file=self.source.name)

    @patch.object(AIService, "generate_quiz_from_lesson")
    def test_form_passes_selection_and_rejects_level_mismatch(self, generate):
        from accounts.models import User, TeacherProfile
        from django.urls import reverse
        teacher = User.objects.create_user(username="source_teacher", role="teacher")
        TeacherProfile.objects.get_or_create(user=teacher)
        session = self.client.session
        session["user_id"] = teacher.pk
        session.save()
        generate.side_effect = ValueError("Test : génération interrompue")
        payload = {
            "niveau": self.lesson.course.niveau, "lesson": self.lesson.pk,
            "source_file": self.source.name, "action": "generate",
        }
        response = self.client.post(reverse("quizzes:teacher_ai"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(generate.call_args.kwargs["source_file"], self.source.name)
        self.assertEqual(response.context["selected_source_file"], self.source.name)
        self.assertEqual(response.context["source_files_by_lesson"][str(self.lesson.pk)], [self.source.name])
        generate.reset_mock()
        payload["niveau"] = "tronc_commun"
        response = self.client.post(reverse("quizzes:teacher_ai"), payload)
        generate.assert_not_called()
        self.assertContains(response, "appartenant au niveau")

    @patch.object(AIService, "_chat", return_value="Explication")
    def test_assistant_rereads_modified_sources_and_ignores_other_lessons(self, chat):
        other = self.folder.parent.parent / "02_autre" / "Sources_IA"
        other.mkdir(parents=True)
        (other / "secret.txt").write_text("AUTRE_LECON", encoding="utf-8")
        service = AIService()
        for text in ("PREMIERE_VERSION", "NOUVELLE_VERSION"):
            self.source.write_text(text, encoding="utf-8")
            service.generate_explanation(self.lesson, "Explique la règle")
            prompt = str(chat.call_args)
            self.assertIn(text, prompt)
            self.assertNotIn("AUTRE_LECON", prompt)
        self.assertNotIn("PREMIERE_VERSION", str(chat.call_args))
        self.source.unlink()
        service.generate_explanation(self.lesson, "Explique la règle")
        self.assertNotIn("NOUVELLE_VERSION", str(chat.call_args))
        self.assertIn("Contenu de secours", str(chat.call_args))

    @override_settings(QUIZ_LESSON_CONTEXT_CHARS=200)
    def test_sources_have_priority_over_long_database_content(self):
        self.lesson.summary = "Résumé secondaire " * 500
        context = self.lesson.get_ai_help()["contenu"]
        self.assertTrue(context.startswith("## Source : Règles.txt"))
        self.assertIn("$P \\Rightarrow Q$", context)
        self.assertLessEqual(len(context), 200)
