import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "sources.json"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(path)


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(text):
    # Keep punctuation, daggers, asterisks, ranges and negation. No clinical rewriting.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).replace("\u00ad", "")).strip()


def page_numbers(spec, total):
    if spec == "all":
        return list(range(1, total + 1))
    result = set()
    for part in spec.split(","):
        if not re.fullmatch(r"\d+(?:-\d+)?", part.strip()):
            raise ValueError(f"Rango de páginas inválido: {part}")
        bounds = [int(x) for x in part.strip().split("-")]
        start, end = (bounds * 2)[:2] if len(bounds) == 1 else bounds
        if not 1 <= start <= end <= total:
            raise ValueError(f"Páginas fuera de 1..{total}: {part}")
        result.update(range(start, end + 1))
    return sorted(result)


def in_range(number, bounds):
    return bounds[0] <= number <= bounds[1]


def provenance(page, line=None):
    result = {key: page[key] for key in ("volume", "source_file", "source_sha256", "pdf_page", "printed_page")}
    if line is not None:
        result.update(line_id=line["id"], bbox=line["bbox"], column=line["column"])
        if "merged_line_ids" in line:
            result["line_ids"] = line["merged_line_ids"]
        if line.get('recovered_from_pdf_margin'):
            result['recovered_from_pdf_margin'] = True
    return result


# Ranges and unspecified fourth characters remain references; never expand them silently.
_SUFFIX = r"(?:\.(?:\d{1,2}|[-–—]))?[†*]?"
CODE_REF = re.compile(r"(?<![A-Za-z0-9])(" + r"[A-Z]\d{2}" + _SUFFIX +
                      r"(?:\s*[-–—]\s*(?:[A-Z]\d{2}|\d{2})" + _SUFFIX + r")?)(?![A-Za-z0-9])")


def code_references(text):
    return list(dict.fromkeys(normalize(m.group(1)) for m in CODE_REF.finditer(text)))
