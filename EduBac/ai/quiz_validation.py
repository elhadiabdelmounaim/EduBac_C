"""Validate one AI-generated QCM without inventing choices or an answer."""
from copy import deepcopy


def validate_question(value, number):
    if not isinstance(value, dict):
        raise ValueError(f"Question {number} invalide.")
    question = deepcopy(value)
    text = question.get("text", question.get("question"))
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Question {number} sans énoncé valide.")
    question["text"] = text

    choices = question.get("choices")
    if not isinstance(choices, list):
        raise ValueError(f"Question {number} : choices doit être une liste.")
    if len(choices) < 2:
        raise ValueError(f"Question {number} doit avoir au moins 2 choix.")
    normalized = []
    for choice in choices:
        if isinstance(choice, str):
            content, correct = choice, False
        elif isinstance(choice, dict):
            content = choice.get("text") or choice.get("label")
            correct = choice.get("is_correct", False)
            if not isinstance(correct, bool):
                raise ValueError(f"Question {number} : is_correct doit être un booléen.")
        else:
            raise ValueError(f"Question {number} : choix invalide.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Question {number} : choix vide ou invalide.")
        normalized.append({"text": content, "is_correct": correct})

    # Preserve mathematical case: f(x) and F(x) are not interchangeable.
    keys = [" ".join(choice["text"].split()) for choice in normalized]
    if len(set(keys)) != len(keys):
        raise ValueError(f"Question {number} : les choix doivent être distincts.")
    marked = [index for index, choice in enumerate(normalized) if choice["is_correct"]]
    if len(marked) > 1:
        raise ValueError(f"Question {number} : plusieurs réponses sont marquées correctes.")

    answer = question.get("correct_answer", question.get("answer"))
    if answer is None or answer == "":
        if len(marked) != 1:
            raise ValueError(f"Question {number} : aucune bonne réponse valide.")
        selected = marked[0]
    else:
        if not isinstance(answer, str) and type(answer) is not int:
            raise ValueError(f"Question {number} : bonne réponse invalide.")
        answer_key = " ".join(str(answer).split())
        if answer_key in keys:
            selected = keys.index(answer_key)
        elif answer_key.lower() in ("a", "b", "c", "d") and ord(answer_key.lower()) - ord("a") < len(normalized):
            selected = ord(answer_key.lower()) - ord("a")
        else:
            raise ValueError(f"Question {number} : la bonne réponse n’appartient pas aux choix.")
        if marked and marked[0] != selected:
            raise ValueError(f"Question {number} : bonne réponse et is_correct contradictoires.")

    for index, choice in enumerate(normalized):
        choice["is_correct"] = index == selected
    question["choices"] = normalized
    question["correct_answer"] = normalized[selected]["text"]
    for field in ("explanation", "hint"):
        if question.get(field) is None:
            question[field] = ""
        if not isinstance(question[field], str):
            raise ValueError(f"Question {number} : {field} doit être du texte.")
    return question
