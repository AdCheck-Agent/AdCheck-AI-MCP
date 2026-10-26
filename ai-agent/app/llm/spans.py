"""Original-text locations. Wire offsets use UTF-16, Python slicing uses code points."""

import re
import unicodedata

from app.schemas.review import Finding


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def quote_spans(source: str, quote: str) -> list[tuple[int, int]]:
    target = " ".join(unicodedata.normalize("NFKC", quote).casefold().split())
    if not target:
        return []
    # Keep the source span of each normalized character, including composed Hangul,
    # combining marks and characters that expand under NFKC/casefold.
    normalized = ""
    positions: list[tuple[int, int]] = []
    previous_end = 0
    for word in re.finditer(r"\S+", source):
        if normalized:
            normalized += " "
            positions.append((previous_end, word.start()))
        prefix = ""
        mapped: list[tuple[int, int]] = []
        for index in range(len(word.group())):
            updated = unicodedata.normalize("NFKC", word.group()[: index + 1]).casefold()
            common = 0
            while common < min(len(prefix), len(updated)) and prefix[common] == updated[common]:
                common += 1
            start = mapped[common][0] if common < len(mapped) else word.start() + index
            mapped[common:] = [(start, word.start() + index + 1)] * (len(updated) - common)
            prefix = updated
        normalized += prefix
        positions.extend(mapped)
        previous_end = word.end()
    return [
        (positions[m.start()][0], positions[m.start() + len(target) - 1][1])
        for m in re.finditer(r"(?=" + re.escape(target) + r")", normalized)
    ]


def locate_findings(source: str, findings: list[Finding]) -> list[Finding]:
    located: list[Finding] = []
    seen: set[tuple] = set()
    for finding in findings:
        for start, end in quote_spans(source, finding.quote):
            wire_start, wire_end = utf16_length(source[:start]), utf16_length(source[:end])
            if finding.start_offset is not None or finding.end_offset is not None:
                if (finding.start_offset, finding.end_offset) != (wire_start, wire_end):
                    continue
            key = (
                wire_start,
                wire_end,
                finding.model_dump_json(
                    exclude={"quote", "start_offset", "end_offset", "detection_type"}
                ),
                tuple(finding.trigger_terms),
            )
            if key in seen:
                continue
            seen.add(key)
            located.append(
                finding.model_copy(
                    update={
                        "quote": source[start:end],
                        "start_offset": wire_start,
                        "end_offset": wire_end,
                        "detection_type": "SEMANTIC",
                    }
                )
            )
    return located


def apply_with_spans(
    source: str, findings: list[Finding]
) -> tuple[str, list[tuple[str, int, int]]] | None:
    """Apply every occurrence and return replacement positions in the revised text."""
    ranges: dict[tuple[int, int], str] = {}
    for finding in findings:
        located = locate_findings(source, [finding])
        if not located or not finding.suggestion:
            return None
        for item in located:
            span = (item.start_offset, item.end_offset)
            if span in ranges and ranges[span] != finding.suggestion:
                return None
            ranges[span] = finding.suggestion
    encoded = source.encode("utf-16-le")
    parts: list[str] = []
    replacements: list[tuple[str, int, int]] = []
    cursor = 0
    length = 0
    for (start, end), replacement in sorted(ranges.items()):
        if start < cursor:
            return None
        prefix = encoded[cursor * 2 : start * 2].decode("utf-16-le")
        parts.extend([prefix, replacement])
        length += utf16_length(prefix)
        replacements.append((replacement, length, length + utf16_length(replacement)))
        length += utf16_length(replacement)
        cursor = end
    parts.append(encoded[cursor * 2 :].decode("utf-16-le"))
    return "".join(parts), replacements
