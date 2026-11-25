"""Literal assertions with source spans; no medical vocabulary or synonym inference.

The grammar recognizes explicit con/sin and no-qualifier constructions. Unknown
paraphrases remain unmatched. Headings define concepts; they are not patient facts.
"""

from dataclasses import dataclass, replace
import re
from ..explanation_constraints import normalize

ARTICLES = {"de", "del", "la", "el", "los", "las", "un", "una", "en"}
METADATA = {
    ("no", "especificado"),
    ("no", "especificada"),
    ("no", "especificados"),
    ("no", "especificadas"),
}


@dataclass(frozen=True)
class Assertion:
    source_id: str
    condition: tuple[str, ...]
    feature: tuple[str, ...]
    value: str
    subject: str
    modality: str
    span: tuple[int, int]
    body_span: tuple[int, int]
    construction: str
    lexemes: tuple = ()

    def trace(self):
        # Refer to original evidence rather than persisting a second diagnosis.
        return {
            "source_id": self.source_id,
            "feature_span": list(self.span),
            "body_span": list(self.body_span),
            "subject": self.subject,
            "modality": self.modality,
            "value": self.value,
            "construction": self.construction,
        }


def _tokens(text, start, end):
    out = []
    for m in re.finditer(r"[^\W_]+|,", text[start:end], re.UNICODE):
        word = normalize(m[0])
        out.append((word, start + m.start(), start + m.end()))
    # Only a trailing metadata label is removed; it is never disease absence.
    if len(out) >= 2 and tuple(x[0] for x in out[-2:]) in METADATA:
        out = out[:-2]
    if out and out[-1][0] in {"sai", "ncop"}:
        out = out[:-1]
    if (
        out
        and out[-1][0] in {"trastorno", "hallazgo"}
        and "(" in text[max(start, out[-1][1] - 2) : out[-1][1]]
    ):
        out = out[:-1]
    return out


def _words(tokens):
    return tuple(w for w, _, _ in tokens if w not in ARTICLES and w != ",")


def _body(text, start, end, input_text):
    subject = "patient" if input_text else "definition"
    mode = "asserted" if input_text else "definition"
    value = "present"
    if not input_text:
        return start, end, subject, mode, value
    raw = text[start:end]
    n = normalize(raw)
    # Prefix recognition uses matched source character lengths, not normalized offsets.
    patterns = [
        (
            r"\s*(?:su|mi|la|el)\s+(?:madre|padre|hermana|hermano|hija|hijo|familiar)\s+",
            "other",
            "asserted",
            "present",
        ),
        (r"\s*antecedentes? de\s+", "patient", "historical", "present"),
        (
            r"\s*(?:no se descarta|no se ha confirmado|posible|sospecha de|hipótesis de)\s+",
            "patient",
            "uncertain",
            "unknown",
        ),
        (
            r"\s*si\s+(?:(?:el|la) paciente\s+)?(?:tuviera|tuviese|presentara|presentase|apareciera|desarrollara)\s+",
            "patient",
            "hypothetical",
            "present",
        ),
        (
            r"\s*(?:(?:el|la) paciente\s+)?(?:no (?:hay|tiene|presenta|padece)|niega|se descarta)\s+",
            "patient",
            "asserted",
            "absent",
        ),
    ]
    for pattern, sub, mod, val in patterns:
        m = re.match(pattern, raw, re.IGNORECASE)
        if m:
            start += m.end()
            subject, mode, value = sub, mod, val
            if mode == "hypothetical":
                comma = text.find(",", start, end)
                if comma >= 0:
                    end = comma
            break
    raw = text[start:end]
    m = re.match(
        r"\s*(?:(?:el|la) paciente\s+)?(?:tiene|presenta|padece|se confirma|se diagnostica|diagnóstico de|diagnóstico:)\s+",
        raw,
        re.IGNORECASE,
    )
    if m:
        start += m.end()
    # Unrecognized contextual language must not be treated as an actual assertion.
    if re.search(
        r"\b(?:si|cuando|posible|sospecha|antecedente|madre|padre)\b",
        normalize(text[start:end]),
    ):
        mode = "uncertain"
    return start, end, subject, mode, value


def extract_assertions(text, source_id, input_text=False):
    result = []
    ranges = (
        [(0, len(text))]
        if not input_text
        else [(m.start(), m.end()) for m in re.finditer(r"[^.;!?]+", text)]
    )
    for start, end in ranges:
        start, end, subject, mode, value = _body(text, start, end, input_text)
        tokens = _tokens(text, start, end)
        if not tokens:
            continue
        if input_text and tokens[-1][0] in {
            "confirmada",
            "confirmado",
            "diagnosticada",
            "diagnosticado",
        }:
            if value == "absent":
                mode = "uncertain"
                value = "unknown"
            tokens = tokens[:-1]
        if not tokens:
            continue
        body = (tokens[0][1], tokens[-1][2])
        words = [x[0] for x in tokens]
        operators = [i for i, w in enumerate(words) if w in {"con", "sin"}]
        if operators:
            condition = _words(tokens[: operators[0]])
            if not condition:
                continue
            for j, i in enumerate(operators):
                chunk = tokens[
                    i + 1 : operators[j + 1] if j + 1 < len(operators) else len(tokens)
                ]
                while chunk and chunk[-1][0] in {"y", "ni", "o", ","}:
                    chunk = chunk[:-1]
                if not chunk:
                    continue
                polarity = "present" if words[i] == "con" else "absent"
                if chunk[0][0] in {
                    "especificar",
                    "mención",
                    "mencion",
                    "mayor",
                    "otra",
                }:
                    continue
                # Positive alternatives do not affirm every listed alternative.
                ambiguous = polarity == "present" and any(w == "o" for w, _, _ in chunk)
                groups = []
                part = []
                for tok in chunk:
                    if tok[0] in {"y", "ni", "o", ","}:
                        if part:
                            groups.append(part)
                            part = []
                    else:
                        part.append(tok)
                if part:
                    groups.append(part)
                for group in groups:
                    feature = _words(group)
                    if feature:
                        result.append(
                            Assertion(
                                source_id,
                                condition,
                                feature,
                                "unknown" if ambiguous else polarity,
                                subject,
                                mode,
                                (group[0][1], group[-1][2]),
                                body,
                                "preposition",
                                tuple(tokens),
                            )
                        )
            # Keep whole-condition denial separate from negative attributes.
            if value == "absent":
                result.append(
                    Assertion(
                        source_id,
                        _words(tokens),
                        (),
                        value,
                        subject,
                        mode,
                        body,
                        body,
                        "condition",
                        tuple(tokens),
                    )
                )
        elif words.count("no") == 1 and words.index("no") > 0:
            i = words.index("no")
            condition = _words(tokens[:i])
            feature = _words(tokens[i + 1 :])
            if condition and feature:
                result.append(
                    Assertion(
                        source_id,
                        condition,
                        feature,
                        "absent",
                        subject,
                        mode,
                        (tokens[i + 1][1], tokens[-1][2]),
                        body,
                        "no_qualifier",
                        tuple(tokens),
                    )
                )
        else:
            result.append(
                Assertion(
                    source_id,
                    _words(tokens),
                    (),
                    value,
                    subject,
                    mode,
                    body,
                    body,
                    "condition",
                    tuple(tokens),
                )
            )
    return result


def align(left, right):
    """Align identical condition/features or a literal minimal no-insertion pair."""
    if left.condition == right.condition and left.feature == right.feature:
        return left, right
    for explicit, plain, reverse in [(left, right, False), (right, left, True)]:
        if (
            explicit.construction == "no_qualifier"
            and not plain.feature
            and plain.condition == explicit.condition + explicit.feature
        ):
            content = [
                tok for tok in plain.lexemes if tok[0] not in ARTICLES and tok[0] != ","
            ]
            tail = content[-len(explicit.feature) :]
            feature_span = (tail[0][1], tail[-1][2]) if tail else plain.span
            inferred = replace(
                plain,
                condition=explicit.condition,
                feature=explicit.feature,
                span=feature_span,
                construction="aligned_positive_qualifier",
            )
            return (inferred, explicit) if reverse else (explicit, inferred)
    return None
