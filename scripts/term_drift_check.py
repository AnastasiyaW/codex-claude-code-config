#!/usr/bin/env python3
"""Check agent prose for terminology drift and overlong sentences.

Two rules borrowed from ASD-STE100 that need no licensed dictionary: one concept
keeps one term, and a sentence stays short. The glossary belongs to the project,
so the check works for any language, including Russian inflection via `stem*`.

Exit codes: 0 clean, 1 findings, 2 check not performed (bad glossary or input).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MAX_WORDS = 25  # ASD-STE100 Issue 9: 20 words procedural, 25 descriptive
WORD = re.compile(r"\w+(?:[-'’]\w+)*")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+|\]\([^)]*\)")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
BLOCK_START = re.compile(r"^\s*([-*+]\s|\d+[.)]\s|>)")
SINGLE_LINE_BLOCK = re.compile(r"^\s*(#{1,6}\s|\|)")
SENTENCE_END = re.compile(r"[.!?…]+(?=\s|$)")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: [{self.kind}] {self.message}"


def _pattern(variant: str) -> re.Pattern[str]:
    stem = variant.strip()
    if not stem or stem == "*":
        raise ValueError("glossary variants must be non-empty")
    if stem.endswith("*"):
        return re.compile(rf"(?<!\w){re.escape(stem[:-1])}\w*(?!\w)", re.IGNORECASE)
    return re.compile(rf"(?<!\w){re.escape(stem)}(?!\w)", re.IGNORECASE)


def load_glossary(path: Path) -> tuple[list[tuple[str, re.Pattern[str]]], int]:
    return parse_glossary(json.loads(path.read_bytes().decode("utf-8-sig")))


def parse_glossary(data: object) -> tuple[list[tuple[str, re.Pattern[str]]], int]:
    if not isinstance(data, dict) or not isinstance(data.get("terms"), dict) or not data["terms"]:
        raise ValueError("glossary needs a non-empty 'terms' object: {canonical: [variants]}")
    unknown = sorted(set(data) - {"terms", "max_words"})
    if unknown:
        raise ValueError(f"unknown glossary keys {unknown}; expected 'terms' and 'max_words'")
    max_words = data.get("max_words", DEFAULT_MAX_WORDS)
    if not isinstance(max_words, int) or isinstance(max_words, bool) or max_words < 5:
        raise ValueError("glossary max_words must be an integer >= 5")
    rules = []
    for canonical, variants in data["terms"].items():
        if not isinstance(variants, list) or not all(isinstance(v, str) for v in variants):
            raise ValueError(f"terms[{canonical!r}] must be a list of strings")
        for variant in variants:
            pattern = _pattern(variant)
            if pattern.fullmatch(canonical):
                raise ValueError(f"variant {variant!r} matches its own canonical term {canonical!r}")
            rules.append((canonical, pattern))
    if not rules:
        raise ValueError("glossary has no variants, so the term check would check nothing")
    return rules, max_words


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Return (line number, text) with fenced code, inline code, URLs and HTML comments blanked."""
    out, fence = [], None
    text = HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for number, line in enumerate(text.splitlines(), start=1):
        marker = FENCE.match(line)
        # CommonMark: a backtick fence's info string cannot contain a backtick
        if marker and marker.group(1)[0] == "`" and "`" in line.strip()[len(marker.group(1)):]:
            marker = None
        if fence is None and marker:
            fence = marker.group(1)
            continue
        if fence is not None:
            # CommonMark: the closing fence uses the same character and is at least as long
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) \
                    and not line.strip()[len(marker.group(1)):].strip():
                fence = None
            continue
        out.append((number, URL.sub(" ", INLINE_CODE.sub(" ", line))))
    if fence is not None:
        raise ValueError(f"unclosed {fence} code fence; the text after it was not checked")
    if not any(WORD.search(line) for _, line in out):
        raise ValueError("no prose left after removing code, URLs and comments")
    return out


def paragraphs(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Join wrapped lines; blank lines and list items start new units.

    Headings are single-line units; table rows are not sentences and are skipped.
    """
    units: list[tuple[int, list[str]]] = []
    for number, line in lines:
        if not line.strip():
            units.append((number, []))
        elif SINGLE_LINE_BLOCK.match(line):
            if not line.lstrip().startswith("|"):
                units.append((number, [line]))
            units.append((number, []))
        elif BLOCK_START.match(line) or not units or not units[-1][1]:
            units.append((number, [line]))
        else:
            units[-1][1].append(line)
    return [(start, "\n".join(body)) for start, body in units if body]


def check(text: str, path: str, rules, max_words: int) -> list[Finding]:
    lines = prose_lines(text)
    findings = []
    for number, line in lines:
        for canonical, pattern in rules:
            for match in pattern.finditer(line):
                if match.group(0).lower() != canonical.lower():
                    findings.append(Finding(path, number, "term-drift",
                                            f'"{match.group(0)}" -> use "{canonical}"'))
    for start, body in paragraphs(lines):
        begin = 0
        for end in [m.end() for m in SENTENCE_END.finditer(body)] + [len(body)]:
            sentence = body[begin:end]
            words = len(WORD.findall(sentence))
            if words > max_words:
                line = start + body[:begin + len(sentence) - len(sentence.lstrip())].count("\n")
                findings.append(Finding(path, line, "long-sentence",
                                        f"{words} words > {max_words}"))
            begin = end
    return findings


SELF_TEST_GLOSSARY = {"terms": {"воркер": ["обработчик*", "исполнител*"], "bolt": ["screw*", "fastener*"]},
                      "max_words": 12}


def self_test() -> int:
    rules, max_words = parse_glossary(SELF_TEST_GLOSSARY)
    must_fail = {
        "inflected synonym": "Перезапусти обработчика очереди.",
        "english synonym": "Tighten the fastener.",
        "long sentence": "Один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать.",
        "wrapped long sentence": "One two three four five six seven\neight nine ten eleven twelve thirteen.",
        "other fence marker does not close": "```\n~~~\n```\nTighten the screw.",
    }
    must_pass = {
        "canonical term": "Перезапусти воркер. Tighten the bolt.",
        "code is not prose": "Запусти `обработчик` и:\n```\nscrew fastener обработчик\n```",
        "short list items": "- Один два три.\n- Четыре пять шесть.",
        "heading is its own unit": "# One two three four five six seven\nOne two three four five six seven.",
        "table row is not a sentence": "| a | b | c | d | e | f | g | h | i | j | k | l | m |",
    }
    failed = [n for n, t in must_fail.items() if not check(t, n, rules, max_words)]
    failed += [n for n, t in must_pass.items() if check(t, n, rules, max_words)]
    for name in failed:
        print(f"self-test FAILED: {name}", file=sys.stderr)
    if not failed:
        print(f"self-test ok: {len(must_fail)} must-fail, {len(must_pass)} must-pass")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="text/markdown files; '-' or none reads stdin")
    parser.add_argument("--glossary", type=Path, help="JSON: {terms: {canonical: [variant, stem*]}, max_words}")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.glossary:
        print("check not performed: --glossary is required", file=sys.stderr)
        return 2
    try:
        rules, max_words = load_glossary(args.glossary)
        # strict UTF-8 for stdin too: a lossy decode would hide every match and exit 0
        sources = [(str(p), p.read_bytes().decode("utf-8-sig")) for p in args.files if str(p) != "-"]
        if not args.files or any(str(p) == "-" for p in args.files):
            sources.append(("<stdin>", sys.stdin.buffer.read().decode("utf-8-sig")))
        empty = [path for path, text in sources if not text.strip()]
        if empty:
            raise ValueError(f"empty input: {', '.join(empty)}")
        findings = [f for path, text in sources for f in check(text, path, rules, max_words)]
    except (OSError, ValueError) as exc:
        print(f"check not performed: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.render())
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
