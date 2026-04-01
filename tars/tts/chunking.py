from __future__ import annotations

import re


_BOUNDARY_PATTERN = re.compile(r"[.!?\n]")


def append_partial(buffer: str, delta: str) -> str:
    if not delta:
        return buffer
    return f"{buffer}{delta}"


def merge_final(buffer: str, final_text: str) -> str:
    cleaned_final = final_text.strip()
    if not cleaned_final:
        return buffer
    cleaned_buffer = buffer.strip()
    if not cleaned_buffer:
        return cleaned_final

    norm_buffer = _normalize(cleaned_buffer)
    norm_final = _normalize(cleaned_final)
    if norm_buffer and norm_final:
        if norm_final in norm_buffer:
            return cleaned_buffer
        if norm_buffer in norm_final:
            return cleaned_final
    return f"{cleaned_buffer} {cleaned_final}"


def split_speakable_segments(
    buffer: str,
    *,
    force: bool,
    min_chars: int = 24,
) -> tuple[list[str], str]:
    text = buffer
    segments: list[str] = []
    while True:
        boundary = _find_boundary(text, min_chars=min_chars)
        if boundary is None:
            break
        segment = text[:boundary].strip()
        if segment:
            segments.append(segment)
        text = text[boundary:].lstrip()

    if force and text.strip():
        segments.append(text.strip())
        text = ""
    return segments, text


def _find_boundary(text: str, *, min_chars: int) -> int | None:
    if len(text) < min_chars:
        return None
    for match in _BOUNDARY_PATTERN.finditer(text):
        idx = match.end()
        if idx >= min_chars:
            return idx
    if len(text) >= max(min_chars * 2, 120):
        return len(text)
    return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]+", "", text.lower())).strip()
