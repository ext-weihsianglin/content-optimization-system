"""Lossless UTF-8-safe splitting with explicit derived-text ranges.

Byte ceilings are deliberately conservative, not reported as tokenizer counts.
No tokenizer weights or GPU are needed. The configured ceiling is below the
shortest endpoint token limit and leaves room for role instructions.
"""

def split_text(text, ceiling, boundaries=()):
    if ceiling < 1:
        raise ValueError("Positive byte ceiling required")
    start = 0
    while start < len(text):
        end, used = start, 0
        while end < len(text) and used + len(text[end].encode()) <= ceiling:
            used += len(text[end].encode())
            end += 1
        if end == start:
            raise ValueError("Ceiling smaller than one Unicode character")
        if end < len(text):
            structural = [boundary for boundary in boundaries if start < boundary <= end]
            if structural:
                end = max(structural)
            else:
                # Oversized individual blocks: preserve content, prefer whitespace.
                boundary = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
                if boundary > start + (end - start) // 2:
                    end = boundary + 1
        yield text[start:end], start, end
        start = end
