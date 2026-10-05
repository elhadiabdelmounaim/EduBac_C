"""
Service de synchronisation des résultats de quiz vers des fichiers Excel
par classe.

Architecture :
  Django DB (Attempt) = source principale
  Excel = export / représentation (jamais la source)

Structure des fichiers :
  media/results/classes/<slug_classe>/results.xlsx
  Une feuille par quiz (titre du quiz, nettoyé).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Q
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="1A6B6B")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)

HEADERS = [
    "Élève",
    "Email",
    "Score (%)",
    "Note /20",
    "Questions",
    "Bonnes",
    "Mauvaises",
    "Temps (min)",
    "Date",
    "Heure",
    "Tentative ID",
]


def _slugify(text: str, max_len: int = 60) -> str:
    text = (text or "classe").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "_", text).strip("_")
    return (text or "classe")[:max_len]


def _sheet_name(title: str) -> str:
    """Nom de feuille Excel valide (max 31 caractères)."""
    name = re.sub(r"[\\/*?:\[\]]", "", (title or "Quiz").strip()) or "Quiz"
    return name[:31]


def class_excel_dir(classroom) -> Path:
    base = Path(settings.MEDIA_ROOT) / "results" / "classes"
    folder = base / f"classe_{_slugify(classroom.name)}_{classroom.pk}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def class_excel_path(classroom) -> Path:
    return class_excel_dir(classroom) / "results.xlsx"


def _style_header_row(ws, headers=HEADERS):
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
        cell.border = THIN
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 28


def _attempt_row_values(attempt) -> list:
    """Construit une ligne de données à partir d'un Attempt."""
    answers = attempt.answers.all()
    total_q = answers.count()
    if total_q == 0 and attempt.quiz_id:
        total_q = attempt.quiz.questions.count() or attempt.quiz.question_count or 0
    bonnes = answers.filter(is_correct=True).count()
    mauvaises = max(0, total_q - bonnes) if total_q else 0
    score_pct = float(attempt.score or 0)
    note_20 = round(score_pct / 5, 1)  # 100% → 20

    temps_min = ""
    if attempt.started_at and attempt.submitted_at:
        delta = (attempt.submitted_at - attempt.started_at).total_seconds()
        temps_min = round(delta / 60, 1)

    student = attempt.student
    return [
        student.get_full_name() or student.username,
        student.email or "",
        score_pct,
        note_20,
        total_q,
        bonnes,
        mauvaises,
        temps_min,
        attempt.submitted_at.strftime("%d/%m/%Y") if attempt.submitted_at else "",
        attempt.submitted_at.strftime("%H:%M") if attempt.submitted_at else "",
        attempt.pk,
    ]


def _find_row_by_attempt_id(ws, attempt_id: int) -> int | None:
    """Cherche la ligne contenant déjà cette tentative (col Tentative ID)."""
    for row in range(2, (ws.max_row or 1) + 1):
        val = ws.cell(row=row, column=11).value
        if val is not None and int(val) == int(attempt_id):
            return row
    return None


def _find_latest_row_for_student(ws, student_name: str, email: str) -> int | None:
    """Pour mise à jour si on ne garde qu'une ligne par élève (dernière tentative)."""
    for row in range(2, (ws.max_row or 1) + 1):
        name = (ws.cell(row=row, column=1).value or "").strip()
        mail = (ws.cell(row=row, column=2).value or "").strip()
        if name == student_name and mail == email:
            return row
    return None


def ensure_workbook(classroom) -> tuple[Workbook, Path]:
    path = class_excel_path(classroom)
    if path.exists():
        try:
            wb = load_workbook(path)
            return wb, path
        except Exception as e:
            logger.warning("Excel corrompu pour classe %s, recréation: %s", classroom.pk, e)
    wb = Workbook()
    # Feuille par défaut vide — on la remplacera
    default = wb.active
    default.title = "_meta"
    default["A1"] = f"Classe: {classroom.name}"
    default["A2"] = f"Niveau: {classroom.get_niveau_display()}"
    default["A3"] = f"ID: {classroom.pk}"
    return wb, path


def get_or_create_sheet(wb: Workbook, quiz_title: str):
    name = _sheet_name(quiz_title)
    if name in wb.sheetnames:
        return wb[name]
    # Éviter conflit avec _meta
    if name == "_meta":
        name = "Quiz"
    ws = wb.create_sheet(title=name)
    _style_header_row(ws)
    return ws


def sync_attempt_to_class_excel(attempt, classroom=None) -> bool:
    """
    Après soumission d'un Attempt, synchronise vers le(s) fichier(s) Excel
    des classes auxquelles l'élève appartient (et dont le teacher a créé le quiz,
    ou toutes les classes de l'élève si classroom est fourni).

    Retourne True si au moins un fichier a été mis à jour.
    Ne lève pas d'exception vers l'appelant (log + return False).
    """
    if not attempt or not attempt.submitted_at:
        return False

    from classrooms.models import ClassroomMember

    try:
        student = attempt.student
        memberships = ClassroomMember.objects.filter(user=student).select_related(
            "classroom", "classroom__teacher"
        )
        if classroom is not None:
            memberships = memberships.filter(classroom=classroom)

        updated = False
        for m in memberships:
            cls = m.classroom
            # Optionnel : ne synchroniser que si le quiz a été créé par le teacher de la classe
            # ou si le teacher est le propriétaire. On synchronise toujours pour les classes de l'élève.
            try:
                ok = _write_attempt_to_classroom(cls, attempt)
                if ok:
                    updated = True
            except Exception as e:
                logger.exception(
                    "Échec sync Excel classe=%s attempt=%s: %s",
                    cls.pk,
                    attempt.pk,
                    e,
                )
        return updated
    except Exception as e:
        logger.exception("sync_attempt_to_class_excel failed: %s", e)
        return False


def _write_attempt_to_classroom(classroom, attempt) -> bool:
    wb, path = ensure_workbook(classroom)
    ws = get_or_create_sheet(wb, attempt.quiz.title)
    values = _attempt_row_values(attempt)

    # Éviter doublons : même Tentative ID → mise à jour
    existing = _find_row_by_attempt_id(ws, attempt.pk)
    if existing:
        row = existing
    else:
        # Nouvelle tentative : on ajoute une ligne (multi-tentatives conservées)
        row = (ws.max_row or 1) + 1
        if row == 2 and ws.cell(row=1, column=1).value is None:
            _style_header_row(ws)

    for col, val in enumerate(values, 1):
        cell = ws.cell(row=row, column=col, value=val)
        cell.border = THIN
        if col in (3, 4, 5, 6, 7, 8):
            cell.alignment = Alignment(horizontal="center")

    # Supprimer feuille _meta vide si d'autres feuilles existent
    if "_meta" in wb.sheetnames and len(wb.sheetnames) > 1:
        # garder _meta pour info, ou la supprimer
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return True


def regenerate_class_excel(classroom) -> Path:
    """
    Régénère entièrement le fichier Excel d'une classe à partir de la DB.
    Source = Attempt des élèves membres de la classe.
    """
    from classrooms.models import ClassroomMember
    from quizzes.models import Attempt

    student_ids = list(
        ClassroomMember.objects.filter(classroom=classroom).values_list("user_id", flat=True)
    )
    attempts = (
        Attempt.objects.filter(
            student_id__in=student_ids,
            submitted_at__isnull=False,
        )
        .select_related("student", "quiz", "quiz__lesson")
        .prefetch_related("answers")
        .order_by("quiz__title", "student__last_name", "student__first_name", "submitted_at")
    )

    # Nouveau workbook propre
    wb = Workbook()
    default = wb.active
    default.title = "_meta"
    default["A1"] = f"Classe: {classroom.name}"
    default["A2"] = f"Niveau: {classroom.get_niveau_display()}"
    default["A3"] = f"ID: {classroom.pk}"
    default["A4"] = f"Élèves: {len(student_ids)}"
    default["A5"] = f"Résultats: {attempts.count()}"

    by_quiz: dict[str, list] = {}
    for a in attempts:
        title = a.quiz.title
        by_quiz.setdefault(title, []).append(a)

    for title, atts in by_quiz.items():
        ws = get_or_create_sheet(wb, title)
        # Réinitialiser contenu (get_or_create a déjà les headers)
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row - 1)
        for i, a in enumerate(atts, start=2):
            for col, val in enumerate(_attempt_row_values(a), 1):
                cell = ws.cell(row=i, column=col, value=val)
                cell.border = THIN
                if col in (3, 4, 5, 6, 7, 8):
                    cell.alignment = Alignment(horizontal="center")

    path = class_excel_path(classroom)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def build_quiz_only_workbook(classroom, quiz) -> Workbook:
    """Workbook temporaire avec uniquement la feuille d'un quiz (pour téléchargement)."""
    from classrooms.models import ClassroomMember
    from quizzes.models import Attempt

    student_ids = list(
        ClassroomMember.objects.filter(classroom=classroom).values_list("user_id", flat=True)
    )
    attempts = (
        Attempt.objects.filter(
            student_id__in=student_ids,
            quiz=quiz,
            submitted_at__isnull=False,
        )
        .select_related("student", "quiz")
        .prefetch_related("answers")
        .order_by("student__last_name", "student__first_name", "submitted_at")
    )

    wb = Workbook()
    ws = wb.active
    ws.title = _sheet_name(quiz.title)
    _style_header_row(ws)
    for i, a in enumerate(attempts, start=2):
        for col, val in enumerate(_attempt_row_values(a), 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.border = THIN
            if col in (3, 4, 5, 6, 7, 8):
                cell.alignment = Alignment(horizontal="center")
    return wb


def delete_class_excel(classroom) -> bool:
    """Supprime le fichier Excel (et le dossier) d'une classe."""
    path = class_excel_path(classroom)
    try:
        if path.exists():
            path.unlink()
        parent = path.parent
        if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
        return True
    except Exception as e:
        logger.exception("Impossible de supprimer Excel classe %s: %s", classroom.pk, e)
        return False


def class_has_excel(classroom) -> bool:
    return class_excel_path(classroom).exists()
