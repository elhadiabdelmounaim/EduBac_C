"""Isolate provider-review calls in tests focused on forms, transport, or structural repairs."""
from unittest.mock import patch


def isolate_protocol_checks(test_case):
    for name, kwargs in (
        ("analyze_context", {"return_value": {"skills": ["Calculs"], "reference_questions": []}}),
        ("validate_and_repair", {"side_effect": lambda service, data, *args:
                                {"reviewed_questions": len(data["questions"]), "checks": []}}),
    ):
        stub = patch("ai.quiz_protocol." + name, **kwargs)
        stub.start()
        test_case.addCleanup(stub.stop)


def isolate_protocol_math(test_case):
    """Keep real canonical and semantic checks in tests dedicated to teacher novelty."""
    analysis = patch("ai.quiz_protocol.analyze_context",
                     return_value={"skills": ["Calculs"], "reference_questions": []})
    analysis.start()
    test_case.addCleanup(analysis.stop)
    review = patch(
        "ai.quiz_protocol.review_questions",
        side_effect=lambda service, questions, indexes, *args: {
            index: {"error": "", "competency": "Calculs", "verification": "mocked_math_review"}
            for index in indexes
        },
    )
    review.start()
    test_case.addCleanup(review.stop)
