"""Authenticated progress and browser timing; no background job or partial quiz exposure."""
import json
import logging
import math
import time
import uuid
from datetime import timedelta
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.decorators import teacher_required
from ai.quiz_metrics import GenerationTrace, LABELS, current_trace
from .models import QuizGenerationRun

logger = logging.getLogger(__name__)


class GenerationTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path.endswith("/generer-envoyer/"):
            request._quiz_received = time.perf_counter()
        return self.get_response(request)


def track_generation(function):
    @wraps(function)
    def wrapped(request, *args, **kwargs):
        if request.method != "POST" or request.POST.get("action", "generate") != "generate":
            return function(request, *args, **kwargs)
        try:
            identifier = uuid.UUID(request.POST["generation_id"]) if request.POST.get("generation_id") else uuid.uuid4()
        except (ValueError, TypeError, AttributeError):
            return JsonResponse({"error": "Identifiant de génération invalide."}, status=400)
        # Indexed retention cleanup touches diagnostics only, not quizzes/results.
        QuizGenerationRun.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()
        run, created = QuizGenerationRun.objects.get_or_create(
            pk=identifier, defaults={"owner": request.user},
        )
        if not created:
            return JsonResponse(
                {"error": "Cette demande a déjà été reçue. Vérifiez « Mes quiz » avant de relancer."},
                status=409,
            )
        trace = GenerationTrace(run, getattr(request, "_quiz_received", None))
        token = current_trace.set(trace)
        try:
            response = function(request, *args, **kwargs)
            response["X-Quiz-Generation-ID"] = trace.id
            response["Server-Timing"] = f'quiz;dur={(time.perf_counter() - trace.started) * 1000:.3f}'
            return response
        except Exception as exc:
            trace.error = getattr(exc, "code", type(exc).__name__)
            raise
        finally:
            try:
                trace.finish()
            finally:
                current_trace.reset(token)
    return wrapped


@teacher_required
@require_http_methods(["GET", "POST"])
def generation_progress(request, generation_id):
    run = QuizGenerationRun.objects.filter(
        pk=generation_id, owner=request.user,
        created_at__gte=timezone.now() - timedelta(days=1),
    ).first()
    if run is None:
        return JsonResponse({"state": "unavailable"}, status=404)
    if request.method == "POST":
        try:
            values = json.loads(request.body)
            allowed = {"http_headers_ms", "html_received_ms", "dom_ready_ms"}
            if (not isinstance(values, dict) or not values or set(values) - allowed
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           or not 0 <= value <= 300000 for value in values.values())):
                raise ValueError()
        except (ValueError, TypeError):
            return JsonResponse({"error": "Mesures invalides."}, status=400)
        if run.state == "running":
            return JsonResponse({"error": "Génération toujours en cours."}, status=409)
        # Only numeric diagnostics supplied by this run's owner; no executable content.
        run.metrics["browser"] = values
        run.save(update_fields=["metrics"])
        logger.info("quiz_browser request_id=%s measurements=%s", run.pk, json.dumps(values))
        return JsonResponse({"saved": True})
    response = JsonResponse({
        "state": run.state, "phase": run.phase, "label": LABELS.get(run.phase, LABELS["request"]),
        "elapsed_ms": round((timezone.now() - run.created_at).total_seconds() * 1000),
    })
    response["Cache-Control"] = "no-store"
    return response
