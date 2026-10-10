"""Validated, atomic persistence for both AI quiz entry points."""
import logging
import time

from django.db import transaction

from ai.quiz_validation import validate_question
from .math_text import normalize_math_text
from .models import Choice, Question, Quiz

logger = logging.getLogger(__name__)


def save_generated_quiz(data, **attributes):
    questions = [validate_question(item, index + 1)
                 for index, item in enumerate(data["questions"])]
    if not questions:
        raise ValueError("Aucune question générée.")
    attributes["question_count"] = len(questions)
    started = time.monotonic()
    with transaction.atomic():
        quiz = Quiz.objects.create(**attributes)
        rows = [Question(
            quiz=quiz, order=index + 1,
            text=normalize_math_text(item["text"]),
            correct_answer=normalize_math_text(item["correct_answer"]),
            explanation=normalize_math_text(item.get("explanation", "")),
            hint=normalize_math_text(item.get("hint", "")),
        ) for index, item in enumerate(questions)]
        Question.objects.bulk_create(rows)
        # Some supported database backends do not return IDs from bulk_create.
        if any(row.pk is None for row in rows):
            rows = list(quiz.questions.order_by("order"))
        Choice.objects.bulk_create([
            Choice(question=row, order=index, text=normalize_math_text(choice["text"]),
                   is_correct=choice["is_correct"])
            for row, item in zip(rows, questions)
            for index, choice in enumerate(item["choices"])
        ])
    logger.info("quiz_persistence questions=%s elapsed=%.3fs", len(questions), time.monotonic() - started)
    return quiz
