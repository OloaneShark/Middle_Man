"""Human and JSON presentation of already-sanitized Context Packs."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from middle_man.gateway.context_models import ContextPack
from middle_man.gateway.indexer import LANGUAGES

_FENCES = {"Python": "python", "JavaScript": "javascript", "TypeScript": "typescript", "TSX": "tsx",
           "JSX": "jsx", "HTML": "html", "CSS": "css", "JSON": "json", "TOML": "toml",
           "YAML": "yaml", "Markdown": "markdown", "Shell": "bash", "PowerShell": "powershell"}


def format_context_pack(pack: ContextPack) -> str:
    metrics = pack.metrics
    lines = ["MIDDLE_MAN CONTEXT PACK", "", "TASK", pack.query.task, "", "REPOSITORY", pack.repository.name,
             "", "ESTIMATED CONTEXT TOKENS (not provider billing or plan usage)",
             f"Candidate full files: {metrics.estimated_raw_candidate_tokens}",
             f"Selected source: {metrics.estimated_selected_tokens}",
             f"Estimated avoided: {metrics.estimated_tokens_avoided} ({metrics.estimated_reduction_percent:.1f}%)",
             f"Files: {metrics.files_selected}/{metrics.candidates_considered} candidates  Excerpts: {metrics.excerpts_selected}",
             f"Mode: {pack.mode.value}  Generation: {pack.generation}  Fingerprint: {pack.fingerprint}"]
    if pack.warnings:
        lines.extend(["", "WARNINGS", *(f"- {warning}" for warning in pack.warnings)])
    for excerpt in pack.excerpts:
        language = _FENCES.get(LANGUAGES.get(Path(excerpt.path).suffix.lower(), "Other"), "")
        fence = "`" * max(3, max((len(match.group()) for match in re.finditer(r"`+", excerpt.text)), default=0) + 1)
        lines.extend(["", "RELATED TEST" if excerpt.path in pack.related_tests else "SOURCE CONTEXT",
                      excerpt.path, f"Lines {excerpt.start_line}-{excerpt.end_line}" + (" (complete file)" if excerpt.complete_file else ""),
                      "Reasons:", *(f"- {reason}" for reason in excerpt.reasons),
                      fence + language, excerpt.text.rstrip("\n"), fence])
    return "\n".join(lines) + "\n"


def context_pack_dict(pack: ContextPack) -> dict[str, object]:
    data = asdict(pack)
    data["selected_files"] = pack.selected_files
    data["selected_symbols"] = pack.selected_symbols
    data["estimated_token_basis"] = "ceil(UTF-8 bytes / 4); source text only; not provider billing"
    data["baseline"] = "complete current text of relevance candidates considered"
    return data


def save_context_pack_json(pack: ContextPack, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(context_pack_dict(pack), indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return destination
