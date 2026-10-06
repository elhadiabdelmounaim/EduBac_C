"""Normalize math text for storage, and render plain-text exports when needed."""

import re


def _is_escaped(text: str, index: int) -> bool:
    slash_count = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        slash_count += 1
        index -= 1
    return slash_count % 2 == 1


def _escape_unmatched_dollar_delimiters(text: str) -> str:
    delimiters = {"$": [], "$$": []}
    index = 0
    while index < len(text):
        if text[index] != "$" or _is_escaped(text, index):
            index += 1
            continue

        if (
            index + 1 < len(text)
            and text[index + 1] == "$"
            and not _is_escaped(text, index + 1)
        ):
            delimiters["$$"].append(index)
            index += 2
        else:
            delimiters["$"].append(index)
            index += 1

    unmatched = []
    for delimiter, positions in delimiters.items():
        if len(positions) % 2:
            unmatched.append((positions[-1], delimiter))

    for index, delimiter in sorted(unmatched, reverse=True):
        escaped = "".join("\\" + char for char in delimiter)
        text = text[:index] + escaped + text[index + len(delimiter):]
    return text


def normalize_math_text(value: object) -> str:
    """Trim math text and normalize supported delimiters without removing LaTeX."""
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(
        r"\\\[(.*?)\\\]",
        lambda match: "$$" + match.group(1) + "$$",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\\\((.*?)\\\)",
        lambda match: "$" + match.group(1) + "$",
        text,
        flags=re.DOTALL,
    )
    return _escape_unmatched_dollar_delimiters(text)


def _legacy_latex_to_plain(text: str) -> str:
    """Fallback for environments where pylatexenc is unavailable."""
    s = text.replace("$$", "").replace("$", "")
    s = re.sub(r"\\\(|\\\)", "", s)
    s = re.sub(r"\\\[|\\\]", "", s)
    s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\\sqrt\{([^{}]+)\}", r"√(\1)", s)
    s = re.sub(r"\\sqrt", "√", s)
    s = re.sub(r"\\cdot", "·", s)
    s = re.sub(r"\\times", "×", s)
    s = re.sub(r"\\div", "÷", s)
    s = re.sub(r"\\leq", "≤", s)
    s = re.sub(r"\\geq", "≥", s)
    s = re.sub(r"\\neq", "≠", s)
    s = re.sub(r"\\approx", "≈", s)
    s = re.sub(r"\\infty", "∞", s)
    s = re.sub(r"\\pi", "π", s)
    s = re.sub(r"\\in", "∈", s)
    s = re.sub(r"\\rightarrow", "→", s)
    s = re.sub(r"\\to", "→", s)
    s = re.sub(r"\\left|\\right", "", s)
    s = re.sub(r"\\text\{([^{}]+)\}", r"\1", s)
    s = re.sub(r"\\mathrm\{([^{}]+)\}", r"\1", s)

    superscripts = str.maketrans("0123456789+-n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ")
    s = re.sub(
        r"([A-Za-z0-9π)])\^\{?([0-9n+-]+)\}?",
        lambda match: match.group(1) + match.group(2).translate(superscripts),
        s,
    )
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def latex_to_plain(value: object) -> str:
    """Convert LaTeX to readable plain text for non-HTML exports."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return text

    text = re.sub(r"\\\((.*?)\\\)", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\\\[(.*?)\\\]", r"\1", text, flags=re.DOTALL)
    try:
        from pylatexenc.latex2text import LatexNodes2Text
    except ImportError:
        return _legacy_latex_to_plain(text)
    return LatexNodes2Text().latex_to_text(text).strip()
