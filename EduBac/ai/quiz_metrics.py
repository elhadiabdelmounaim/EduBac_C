"""Content-free timings and real progress for the existing synchronous pipeline."""
import json
import logging
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

logger = logging.getLogger(__name__)
current_trace = ContextVar("quiz_generation_trace", default=None)
LABELS = {
    "request": "Préparation de la demande…",
    "catalog": "Recherche des ressources disponibles…",
    "resources": "Lecture des ressources sélectionnées…",
    "analysis": "Analyse pédagogique du sujet et des ressources…",
    "history": "Consultation de l’historique des questions…",
    "prompt": "Préparation des questions…",
    "generation": "Génération des questions…",
    "math": "Vérification mathématique des réponses et explications…",
    "novelty": "Comparaison avec l’historique et contrôle des doublons…",
    "repair": "Correction ciblée des questions refusées…",
    "quota_wait": "Attente du quota du fournisseur IA ; reprise automatique…",
    "persistence": "Enregistrement du quiz validé…",
    "render": "Préparation de l’affichage…",
    "complete": "Quiz validé et enregistré.",
    "failed": "La génération s’est arrêtée ; consultez le message d’erreur.",
}


class GenerationTrace:
    def __init__(self, run=None, started=None):
        self.run = run
        self.id = str(run.pk) if run else str(uuid.uuid4())
        self.started = time.perf_counter() if started is None else started
        self.phase = "request"
        self.timings = defaultdict(float)
        self.counts = defaultdict(int)
        self.calls = []
        self.refused = defaultdict(set)
        self.usage = defaultdict(int)
        self.quiz_id = None
        self.error = None

    def reject(self, stage, indexes):
        self.refused[stage].update(indexes)
        self.counts[stage + "_rejected_slots"] = len(self.refused[stage])

    def publish(self, phase):
        self.phase = phase
        if self.run is not None:
            from django.db import DatabaseError, transaction
            from django.utils import timezone
            try:
                with transaction.atomic():
                    type(self.run).objects.filter(pk=self.run.pk).update(
                        phase=phase, updated_at=timezone.now(),
                    )
            except DatabaseError:
                # Diagnostic writes must not invalidate a correct quiz.
                logger.warning("quiz_progress_unavailable request_id=%s", self.id)

    @contextmanager
    def span(self, name, publish=True):
        previous = self.phase
        if publish:
            self.publish(name)
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            self.timings[name] += elapsed
            self.counts[name] += 1
            logger.info("quiz_timing request_id=%s phase=%s duration_ms=%.3f",
                        self.id, name, elapsed)
            if publish:
                self.publish(previous)

    def summary(self):
        return {
            "request_id": self.id,
            "server_ms": round((time.perf_counter() - self.started) * 1000, 3),
            "phases_ms": {key: round(value, 3) for key, value in self.timings.items()},
            "phase_calls": dict(self.counts),
            "ai_calls": len(self.calls),
            "api": self.calls,
            "tokens_reported": dict(self.usage),
            "error_code": self.error,
        }

    def finish(self):
        from django.utils import timezone
        state = "complete" if self.quiz_id is not None else "failed"
        summary = self.summary()
        logger.info("quiz_summary %s", json.dumps(summary, separators=(",", ":")))
        if self.run is not None:
            from django.db import DatabaseError, transaction
            try:
                with transaction.atomic():
                    type(self.run).objects.filter(pk=self.run.pk).update(
                        phase=state, state=state, metrics=summary,
                        quiz_id=self.quiz_id, updated_at=timezone.now(),
                    )
            except DatabaseError:
                logger.warning("quiz_progress_unavailable request_id=%s", self.id)
        return summary


@contextmanager
def phase(name, publish=True):
    trace = current_trace.get()
    if trace is None:
        yield
    else:
        with trace.span(name, publish=publish):
            yield


def timed_phase(name, publish=True):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with phase(name, publish):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def provider_response(response, headers_ms=None):
    trace = current_trace.get()
    if trace is None:
        return
    usage = getattr(response, "usage", None)
    trace.last_response = {}
    if usage is not None:
        trace.usage["responses"] += 1
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(usage, field, None)
            if isinstance(value, int):
                trace.usage[field] += value
                trace.last_response[field] = value
    if headers_ms is not None:
        trace.timings["api_headers"] += headers_ms
        trace.counts["api_headers"] += 1
        trace.last_response["http_headers_ms"] = round(headers_ms, 3)
