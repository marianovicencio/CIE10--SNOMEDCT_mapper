"""Literal text helpers. Normalization never rewrites the stored source."""

import re
from cie10.explanations.explanation_constraints import normalize


STOP = {
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "en",
    "y",
    "o",
    "con",
    "sin",
    "no",
    "un",
    "una",
    "especificada",
    "especificado",
    "primaria",
    "primario",
}


def clean(text):
    text = normalize(text)
    text = re.sub(r"\((?:trastorno|hallazgo)\)", "", text)
    text = re.sub(r"\b(?:no especificad[ao]s?|sin especificar|sai)\b", "", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def absence(text):
    text = normalize(text)
    out = set()
    for m in re.finditer(r"\bsin ([a-z]{4,})(?: (?:o|ni|y) ([a-z]{4,}))?", text):
        out.update(
            w
            for w in m.groups()
            if w and w not in {"especificar", "complicaciones", "otra", "otras"}
        )
    return out


def core(text):
    text = normalize(text)
    text = re.split(r"\bsin\b", text)[0]
    return " ".join(
        w[:-1] if w.endswith("s") and len(w) > 5 else w
        for w in clean(text).split()
        if w not in STOP
    )
