"""Safe validation and persistence for teacher-supplied quiz JSON files."""
from decimal import Decimal, InvalidOperation
import json
import math
import re
import unicodedata

from django.db import transaction

from education.media_library import LEVEL_FOLDERS
from education.models import Course, Lesson
from .math_text import normalize_math_text
from .models import Choice, Question, Quiz

MAX_JSON_BYTES = 1_000_000
MAX_QUESTIONS = 100
MAX_DURATION_MINUTES = 600
MAX_POINTS = Decimal('100.00')
DIFFICULTY_MAP = {
    'easy': 'facile', 'facile': 'facile',
    'medium': 'moyen', 'moyen': 'moyen',
    'hard': 'difficile', 'difficile': 'difficile',
}


class QuizImportError(ValueError):
    """A safe, teacher-readable import validation error."""


def _normal(value):
    value = unicodedata.normalize('NFKD', value)
    return ''.join(char for char in value if not unicodedata.combining(char)).casefold().strip()


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QuizImportError("Le fichier JSON contient une clé répétée.")
        result[key] = value
    return result


def _reject_nonfinite(value):
    raise QuizImportError("Le fichier JSON contient une valeur numérique non valide.")


def _nonempty_text(value, label, max_length):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise QuizImportError(f"{label} doit être un texte non vide de {max_length} caractères maximum.")
    value = value.strip()
    if '\x00' in value:
        raise QuizImportError(f"{label} contient un caractère non valide.")
    return value


def _resolve_level(level_value):
    level = _nonempty_text(level_value, "Le niveau", 100)
    aliases = {}
    valid_codes = {code for code, _label in Course.NIVEAU_CHOICES}
    for code, label in Course.NIVEAU_CHOICES:
        aliases[_normal(code)] = code
        aliases[_normal(label)] = code
    for code, folder in LEVEL_FOLDERS.items():
        if code in valid_codes:
            aliases[_normal(folder)] = code
    resolved = aliases.get(_normal(level))
    if not resolved:
        raise QuizImportError(
            "Le niveau du fichier n’existe pas dans le programme. "
            "Utilisez le code ou le nom du niveau EduBac."
        )
    return resolved


def _resolve_lesson(level_code, lesson_value):
    title = _nonempty_text(lesson_value, "La leçon", 255)
    matches = list(
        Lesson.objects.filter(course__niveau=level_code)
        .select_related('course')
        .order_by('course__order', 'order', 'pk')
    )
    matches = [lesson for lesson in matches if _normal(lesson.title) == _normal(title)]
    if not matches:
        raise QuizImportError(
            "La leçon indiquée n’existe pas pour ce niveau. Vérifiez le titre et le niveau du fichier."
        )
    if len(matches) > 1:
        raise QuizImportError(
            "Plusieurs leçons correspondent à ce titre pour le niveau choisi. "
            "Le fichier doit préciser une leçon non ambiguë."
        )
    return matches[0]


def _parse_points(value, number):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise QuizImportError(f"Question {number} : indiquez un nombre de points positif.")
    try:
        points = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise QuizImportError(f"Question {number} : indiquez un nombre de points valide.") from None
    if not points.is_finite() or points <= 0 or points > MAX_POINTS:
        raise QuizImportError(f"Question {number} : les points doivent être compris entre 0 et 100.")
    if points.as_tuple().exponent < -2:
        raise QuizImportError(f"Question {number} : les points ne peuvent pas avoir plus de deux décimales.")
    return points.quantize(Decimal('0.01'))


def _parse_question(value, number, seen_ids):
    if not isinstance(value, dict):
        raise QuizImportError(f"Question {number} : l’objet question est invalide.")
    question_id = _nonempty_text(value.get('id'), f"Question {number} : l’identifiant", 64)
    if question_id in seen_ids:
        raise QuizImportError(f"Question {number} : l’identifiant « {question_id} » est répété.")
    seen_ids.add(question_id)

    if value.get('type') != 'multiple_choice':
        raise QuizImportError(
            f"Question {number} : seul le type « multiple_choice » à réponse unique est pris en charge."
        )
    text = _nonempty_text(value.get('statement'), f"Question {number} : l’énoncé", 20_000)
    choices_data = value.get('choices')
    if not isinstance(choices_data, list) or len(choices_data) != 4:
        raise QuizImportError(f"Question {number} : un QCM doit contenir exactement quatre choix.")

    choice_ids = set()
    choice_texts = set()
    choices = []
    for choice_number, choice in enumerate(choices_data, 1):
        if not isinstance(choice, dict):
            raise QuizImportError(f"Question {number} : le choix {choice_number} est invalide.")
        choice_id = _nonempty_text(
            choice.get('id'), f"Question {number} : l’identifiant d’un choix", 64,
        )
        choice_text = _nonempty_text(
            choice.get('text'), f"Question {number} : le texte d’un choix", 500,
        )
        if choice_id in choice_ids:
            raise QuizImportError(f"Question {number} : les identifiants de choix doivent être uniques.")
        if re.sub(r'\s+', ' ', choice_text) in choice_texts:
            raise QuizImportError(f"Question {number} : les quatre choix doivent être différents.")
        choice_ids.add(choice_id)
        choice_texts.add(re.sub(r'\s+', ' ', choice_text))
        choices.append({'id': choice_id, 'text': choice_text})

    answer_id = _nonempty_text(
        value.get('correct_answer'), f"Question {number} : la bonne réponse", 64,
    )
    if answer_id not in choice_ids:
        raise QuizImportError(
            f"Question {number} : la bonne réponse ne correspond à aucun identifiant de choix."
        )

    difficulty = value.get('difficulty')
    if not isinstance(difficulty, str) or difficulty.strip().casefold() not in DIFFICULTY_MAP:
        raise QuizImportError(
            f"Question {number} : la difficulté doit être easy, medium, hard, facile, moyen ou difficile."
        )
    explanation = value.get('explanation', '')
    hint = value.get('hint', '')
    for field, content in (('explanation', explanation), ('hint', hint)):
        if content is None:
            content = ''
        if not isinstance(content, str) or len(content) > 20_000 or '\x00' in content:
            raise QuizImportError(f"Question {number} : le champ « {field} » est invalide.")
        if field == 'explanation':
            explanation = content.strip()
        else:
            hint = content.strip()

    points = _parse_points(value.get('points'), number)
    return {
        'id': question_id,
        'text': text,
        'choices': choices,
        'correct_answer_id': answer_id,
        'difficulty': DIFFICULTY_MAP[difficulty.strip().casefold()],
        'points': points,
        'explanation': explanation,
        'hint': hint,
    }


def validate_quiz_json(upload, selected_lesson=None):
    if upload is None:
        raise QuizImportError("Sélectionnez un fichier JSON à importer.")
    if not upload.name.lower().endswith('.json'):
        raise QuizImportError("Le fichier doit porter l’extension .json.")
    if upload.size > MAX_JSON_BYTES:
        raise QuizImportError("Le fichier JSON ne doit pas dépasser 1 Mio.")
    try:
        raw = upload.read(MAX_JSON_BYTES + 1)
    except OSError:
        raise QuizImportError("Le fichier n’a pas pu être lu.") from None
    if len(raw) > MAX_JSON_BYTES:
        raise QuizImportError("Le fichier JSON ne doit pas dépasser 1 Mio.")
    try:
        document = json.loads(
            raw.decode('utf-8-sig'),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except QuizImportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise QuizImportError("Le fichier n’est pas un JSON UTF-8 valide.") from None

    if not isinstance(document, dict) or not isinstance(document.get('quiz'), dict):
        raise QuizImportError("Le fichier doit contenir un objet « quiz ».")
    quiz_data = document['quiz']
    title = _nonempty_text(quiz_data.get('title'), "Le titre du quiz", 255)
    if selected_lesson is None:
        level_code = _resolve_level(quiz_data.get('level'))
        lesson = _resolve_lesson(level_code, quiz_data.get('lesson'))
    else:
        level_code = selected_lesson.course.niveau
        lesson = selected_lesson
        file_level = quiz_data.get('level')
        if file_level not in (None, '') and _resolve_level(file_level) != level_code:
            raise QuizImportError(
                "Le niveau du fichier ne correspond pas au niveau choisi dans le formulaire."
            )
        file_lesson = quiz_data.get('lesson')
        if file_lesson not in (None, ''):
            file_lesson = _nonempty_text(file_lesson, "La leçon", 255)
            if _normal(file_lesson) != _normal(selected_lesson.title):
                raise QuizImportError(
                    "La leçon du fichier ne correspond pas à celle choisie dans le formulaire."
                )

    duration = quiz_data.get('duration')
    if type(duration) is not int or not 1 <= duration <= MAX_DURATION_MINUTES:
        raise QuizImportError("La durée du quiz doit être un nombre entier entre 1 et 600 minutes.")
    questions_data = quiz_data.get('questions')
    if not isinstance(questions_data, list) or not 1 <= len(questions_data) <= MAX_QUESTIONS:
        raise QuizImportError(f"Le fichier doit contenir entre 1 et {MAX_QUESTIONS} questions.")

    seen_ids = set()
    questions = [
        _parse_question(question, number, seen_ids)
        for number, question in enumerate(questions_data, 1)
    ]
    description = quiz_data.get('description', '')
    if not isinstance(description, str) or len(description) > 4000 or '\x00' in description:
        raise QuizImportError("La description du quiz est invalide.")
    difficulty_counts = {}
    for question in questions:
        difficulty_counts[question['difficulty']] = difficulty_counts.get(
            question['difficulty'], 0,
        ) + 1
    overall_difficulty = max(
        ('facile', 'moyen', 'difficile'),
        key=lambda item: (difficulty_counts.get(item, 0), -('facile', 'moyen', 'difficile').index(item)),
    )
    return {
        'title': title,
        'description': description.strip(),
        'lesson': lesson,
        'level': level_code,
        'duration': duration,
        'difficulty': overall_difficulty,
        'questions': questions,
    }


def _parse_seconds_per_question(value):
    if isinstance(value, bool):
        raise QuizImportError("Le temps par question doit être compris entre 5 et 600 secondes.")
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str) and value.strip().isdecimal():
        seconds = int(value.strip())
    else:
        raise QuizImportError("Indiquez un temps entier par question, entre 5 et 600 secondes.")
    if not 5 <= seconds <= 600:
        raise QuizImportError("Le temps par question doit être compris entre 5 et 600 secondes.")
    return seconds


def create_quiz_from_json(
    upload, teacher, *, selected_lesson=None, seconds_per_question=None,
):
    """Validate fully before atomically creating an editable draft, without an AI call."""
    data = validate_quiz_json(upload, selected_lesson=selected_lesson)
    question_count = len(data['questions'])
    seconds_per_question = (
        _parse_seconds_per_question(seconds_per_question)
        if seconds_per_question is not None
        else max(1, math.ceil(data['duration'] * 60 / question_count))
    )
    with transaction.atomic():
        quiz = Quiz.objects.create(
            title=data['title'],
            description=data['description'],
            lesson=data['lesson'],
            duration=data['duration'],
            seconds_per_question=seconds_per_question,
            question_count=question_count,
            difficulty=data['difficulty'],
            status='draft',
            created_by=teacher,
        )
        for order, source in enumerate(data['questions'], 1):
            correct = next(
                choice for choice in source['choices']
                if choice['id'] == source['correct_answer_id']
            )
            question = Question.objects.create(
                quiz=quiz,
                order=order,
                text=normalize_math_text(source['text']),
                correct_answer=normalize_math_text(correct['text']),
                explanation=normalize_math_text(source['explanation']),
                hint=normalize_math_text(source['hint']),
                difficulty=source['difficulty'],
                points=source['points'],
            )
            Choice.objects.bulk_create([
                Choice(
                    question=question,
                    order=index,
                    text=normalize_math_text(choice['text']),
                    is_correct=choice['id'] == source['correct_answer_id'],
                )
                for index, choice in enumerate(source['choices'])
            ])
    return quiz
