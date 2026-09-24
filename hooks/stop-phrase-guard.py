#!/usr/bin/env python3
"""Stop hook: detect behavioral regression phrases in the final assistant message.

Based on the AMD Claude Code regression investigation (issue #42796, April 2026).
The investigator identified five phrase categories that signal a degraded agent:
ownership dodging, permission-seeking, premature stopping, known-limitation
labeling, and session-length excuses. In a healthy period these phrases never
appeared; post-regression they fired 173 times in 17 days.

When a match is found, the hook blocks the Stop event via a JSON response, forcing
the agent to either actually finish the work or explicitly explain the limitation.
This converts behavioral degradation from an invisible drift into a loud signal.

Register in ~/.claude/settings.json:
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python path/to/stop-phrase-guard.py",
        "statusMessage": "Checking for regression phrases..."
      }]
    }]
  }
}

Reference: https://github.com/anthropics/claude-code/issues/42796
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

# Phrase categories from the AMD investigation. Lowercase-matched against the
# final assistant message. Each entry: (category_name, [patterns]).
# Patterns are regex, case-insensitive, word-boundary aware.
PHRASE_CATEGORIES: list[tuple[str, list[str]]] = [
    (
        "ownership_dodging",
        [
            r"not caused by my changes",
            r"pre[- ]existing (issue|bug|problem)",
            r"this was already (broken|failing)",
            r"existing (issue|bug|problem) (in|with) the code",
            r"not (related to|a result of) my (change|edit)",
        ],
    ),
    (
        "permission_seeking",
        [
            r"should I (continue|proceed|keep going)\??",
            r"want me to keep going\??",
            r"shall I proceed\??",
            r"do you want me to continue\??",
            r"would you like me to proceed\??",
        ],
    ),
    (
        "premature_stopping",
        [
            r"good (stopping|stop) point",
            r"natural checkpoint",
            r"reasonable place to (pause|stop)",
            r"good place to (pause|stop)",
            r"stopping (here|for now)",
        ],
    ),
    (
        "known_limitation",
        [
            r"known limitation",
            r"out of scope",
            r"future work",
            r"left (for|as) (future|follow[- ]up) work",
            r"beyond the scope of this",
        ],
    ),
    (
        "session_length_excuse",
        [
            r"continue in a new session",
            r"(session|context) is (getting (long|full)|filling up|running out)",
            r"(approaching|hitting) (context|the) limit",
            r"pick this up in a fresh session",
        ],
    ),
    (
        "deferral_via_indicative_proposal",
        [
            # The same deferral wearing a statement instead of a question:
            # naming a cheap reversible improvement and leaving it undone.
            # "limit: 50 is hardcoded, raising it is nearly free" ends a turn
            # exactly as "shall I raise it?" does, and slips past the
            # question-shaped patterns below. Deliberately narrow: it needs an
            # explicit "this is cheap/easy" claim, which is what marks the
            # change as one the agent was already authorised to make. A finding
            # that genuinely needs a decision does not advertise itself as free.
            r"(поднимается|правится|чинится|решается|делается)\s+(почти\s+)?(бесплатно|в одну строку|одной строкой|тривиально)",
            r"(легко|тривиально|дёшево|дешево)\s+(поднять|поправить|починить|увеличить|исправить|заменить)",
            r"(raising|bumping|fixing|changing) it is (nearly |almost )?free",
            r"(trivial|cheap|easy) to (raise|bump|fix|increase|change)\b",
            r"\bone-line (fix|change)\b[^.?!\n]{0,40}\b(would|could)\b",
        ],
    ),
    (
        "deferral_via_next_step_question",
        [
            # Ending the turn by asking "what next" / offering a menu of options /
            # asking permission, instead of just doing the planned work in order.
            # User directive 2026-06-07: "не откладываем, делаем всё по очереди".
            r"что (дальше|делаем дальше|теперь делаем|по плану дальше)\b",
            r"что (приоритетн|важнее|выбираешь|предпочитаешь)",
            r"что из (этого|них|трёх|двух|перечисленн|предложенн)",
            r"скаж(ешь|и)[^.?!\n]{0,40}(сделаю|продолжу|заведу|подниму|пройд|починю|дам команду|возьмусь)",
            r"хочешь[^.?!\n]{0,40}(сделаю|сделать|продолжу|заведу|подниму|починю|возьмусь)",
            r"по любому из (этих|трёх|двух|них|пунктов)",
            r"\bили (всё ок|отдыхаем|ждём|двигаемся дальше)\b",
            # binary-choice deferral: "<do X> или оставить/не трогать/потом?" — offering
            # to skip planned work instead of doing it. (gap found 2026-06-16: a real
            # "прогнать ... или оставить?" ending slipped past every pattern above.)
            r"\bили (оставить|оставля|не трога|потом|как есть|подожд|скип)",
            r"\bor (leave it|leave as|should i leave|skip it|skip this)\b",
            r"what (would you like|next|should i (do|tackle))\b",
            r"\bsay the word\b",
            r"let me know (which|if you|what you)\b",
            r"pick (one|an option|which)\b",
        ],
    ),
    (
        "offer_and_defer",
        [
            # Offering to do remaining work "later / if you say so" instead of doing it NOW.
            # User directive 2026-06-09: "доделывай нормально ... всегда всё доделываем до конца".
            r"осталось( бы)? (доделать|сделать|починить|доводить|закрыть)",
            r"по[- ]хорошему[^.?!\n]{0,80}(скаж|если|можно|надо|стоит|сделать|доделать)",
            r"не срочно[^.?!\n]{0,40}(скаж|сделаю|если|можно|потом)",
            r"могу[^.?!\n]{0,50}если[^.?!\n]{0,30}(скаж|захочешь|нужно|надо)",
            r"если (захочешь|нужно|надо|пожелаешь)[^.?!\n]{0,40}(сделаю|починю|подниму|заведу|могу)",
            r"оставля[ею] (на потом|на будущее|как есть)",
            r"\(не срочно",
        ],
    ),
    (
        "private_credential_refusal",
        [
            # This closed working chat is inside the configured trust boundary.
            # A blanket refusal to show the exact credential needed for the
            # requested work contradicts rules/secrets-as-data.md. Public or
            # external disclosure is filtered separately below.
            r"не\s+(?:вывожу|показываю|раскрываю|публикую|передаю)[^.?!\n]{0,70}(?:уч[её]тн(?:ые|ых)\s+данн|логин|парол|токен|доступ)[^.?!\n]{0,70}(?:переписк|чат)",
            r"(?:не\s+буду|отказываюсь)\s+(?:выводить|показывать|раскрывать|публиковать|передавать)[^.?!\n]{0,70}(?:уч[её]тн(?:ые|ых)\s+данн|логин|парол|токен|доступ)",
            r"(?:i\s+)?(?:do not|don't|won't|cannot|can't)\s+(?:show|reveal|print|share|output)[^.?!\n]{0,70}(?:credentials?|login|password|token|access)[^.?!\n]{0,70}(?:chat|conversation)",
        ],
    ),
]

# Suppress false positives: if the agent is explicitly ACKNOWLEDGING the phrase
# as a known anti-pattern (meta-discussion), do not flag. Heuristic: if the
# message mentions "anti-pattern", "regression", "stop-phrase-guard", "#42796",
# etc. near the matched phrase, it is likely meta-discussion.
META_DISCUSSION_MARKERS = [
    "anti-pattern",
    "regression",
    "stop-phrase-guard",
    "#42796",
    "AMD investigation",
    "behavioral tell",
    "reasoning regression",
    "finish-the-task",
    "next-step-guard",
    "deferral_via_next_step",
    "deferral_via_indicative_proposal",
    "не откладыва",
]

# Strong meta markers: naming THIS guard or its categories means the message is ABOUT the
# hook (documenting it / quoting example trigger phrases), not an actual deferral. Their
# presence ANYWHERE suppresses the whole message — avoids the guard tripping on its own docs.
STRONG_META_MARKERS = [
    "stop-phrase-guard",
    "offer_and_defer",
    "deferral_via_next_step",
    "deferral_via_indicative_proposal",
    "regression phrase guard",
    "phrase guard",
    "regression phrase",
]

_DISCLOSURE_BOUNDARY = re.compile(
    r"\b(public|external|third[- ]party)\b|публичн|внешн(?:ий|ему|юю|яя)|треть(?:ей|им)\s+сторон",
    re.IGNORECASE,
)
_BOUNDARY_OBJECT = re.compile(
    r"\b(repo(?:sitory)?|github|visibility|publication|recipient|boundary)\b|"
    r"репозитор|видимост|публикац|получател|границ",
    re.IGNORECASE,
)
_MEASURED_EVIDENCE = re.compile(
    r"\b(measured|verified|confirmed|checked|observed)\b|"
    r"механическ|измерен|проверен|подтвержд|наблюдаем",
    re.IGNORECASE,
)
_USER_WORK_DIRECTIVE = re.compile(
    r"(?i)\b(?:выдели(?:те)?|скопируй(?:те)?|вставь(?:те)?|введи(?:те)?|набер(?:и|ите)|"
    r"выполни(?:те)?|запусти(?:те)?|открой(?:те)?|подтверди(?:те)?|пришли(?:те)?|"
    r"используй(?:те)?|установи(?:те)?|настрой(?:те)?|создай(?:те)?|перейди(?:те)?|"
    r"нажми(?:те)?|загрузи(?:те)?|copy|paste|enter|run|execute|open|confirm|send|"
    r"provide|type|use|set|configure|create|navigate|click|tap|upload)\b"
)
_HUMAN_ONLY_DIRECTIVE = re.compile(
    r"(?i)^(?:подтверди(?:те)?|пришли(?:те)?|confirm|send|provide)$"
)
_PHYSICAL_ONLY_DIRECTIVE = re.compile(
    r"(?i)^(?:открой(?:те)?|нажми(?:те)?|open|click|tap)$"
)
_COMPLETED_MACHINE_PREFIX = re.compile(
    r"(?i)\b(?:я|i|we)\s+(?:(?:уже|already)\s+)?(?:запустил[аи]?|выполнил[аи]?|настроил[аи]?|"
    r"started|ran|executed|configured)\b|\b(?:процесс|команда|cli)\s+(?:уже\s+)?"
    r"(?:запущен[а]?|ожидает)|\bprocess\s+is\s+(?:running|waiting)\b"
)
_HUMAN_ONLY_INPUT = re.compile(
    r"(?i)\b(?:otp|captcha|2fa|one[- ]time code|phone number|physical confirmation|"
    r"код(?:а)?\s+(?:telegram|из\s+telegram|sms|из\s+sms)|номер\s+телефона|капч|"
    r"биометр\w*|физическ(?:ое|ого)\s+подтверждени(?:е|я))\b"
)
_PHYSICAL_HUMAN_BOUNDARY = re.compile(
    r"(?i)\b(?:physical confirmation|biometric|authenticator app|on (?:your )?phone|"
    r"биометр\w*|физическ(?:ое|ого)\s+подтверждени(?:е|я)|на (?:вашем\s+)?телефон\w*|"
    r"в приложении\s+на\s+телефон\w*)\b"
)
_EXPLICIT_TUTORIAL_REQUEST = re.compile(
    r"(?i)^\s*(?:а\s+)?(?:"
    r"как\s+(?:мне|нам|самой|самому|самостоятельно|вручную|[а-яё]+(?:ть|ти|чь))\b|"
    r"how\s+(?:to\b|(?:do|can|should)\s+(?:i|we)\b)|"
    r"(?:can|could|would)\s+you\s+(?:show|tell)\s+me\s+how\s+to\b|"
    r"(?:покажи(?:те)?|напиши(?:те)?|дай(?:те)?)\b[^\n]*(?:как|команд|инструкц|шаг)|"
    r"(?:show|provide|give)\b[^\n]*(?:how\s+to|command|instruction|steps)"
    r")"
)
# Measured 2026-09-24: run as one regex by finditer, the command-shape
# alternatives re-read a span from every start inside it -- a [\w.-] run, a
# whitespace block, a fence line -- and an unclosed inline span backtracks
# within one start: 3.1 s on 20k characters of "a/b.b.b...", ~100 s on 100k,
# with no timeout on this Stop hook. Each alternative below is searched by a
# scan that is linear for exactly its text; edit a pattern, re-prove its scan.
_INLINE_END = re.compile(r"[`\n]")
_INLINE_MARK = re.compile(r"(?i)\$env:|https?://|--?[a-z]|[a-z]:\\|/[\w.-]")
_WORD_HEAD = re.compile(r"(?i)\b[a-z]")
_WORD_RUN = re.compile(r"[\w.-]*")
_WORD_FLAG = re.compile(r"(?i)\s+(?:--?[a-z][\w-]*|https?://\S+|[a-z]:\\\S+|/[\w.-]+)")
_LINE_START = re.compile(r"(?m)^")
_LINE_LEAD = re.compile(r"\s*")
_PROMPT = re.compile(r"(?i)(?:ps>\s*|\$\s+)\S+")


def _scan_plain(message: str, rx: re.Pattern):
    """Linear as it is: only a literal `$env:` can start it."""

    def find(pos: int):
        match = rx.search(message, pos)
        return match.start() if match else None

    return find


def _scan_fences(message: str, rx: re.Pattern):
    """An opener needs a newline after it and a closer after that newline.

    A later opener has no nearer newline and no later closer, so the first
    opener from pos decides for every one after it.
    """
    last_fence = message.rfind("```")
    newline = -1

    def find(pos: int):
        nonlocal newline
        opener = message.find("```", pos)
        if opener < 0:
            return None
        if newline < opener + 3:  # else the newline found last is still the next one
            newline = message.find("\n", opener + 3)
        return opener if 0 <= newline < last_fence else None

    return find


def _scan_inline(message: str, rx: re.Pattern):
    """A span runs to the first backtick or newline after its opener.

    It matches when that is a backtick and a mark lies in between; no mark
    holds a backtick or a newline, so no two openers read the same stretch.
    """

    def find(pos: int):
        while (opener := message.find("`", pos)) >= 0:
            end = _INLINE_END.search(message, opener + 1)
            if end is None:
                return None
            if end.group() == "`" and _INLINE_MARK.search(message, opener + 1, end.start()):
                return opener
            pos = end.start()
        return None

    return find


def _scan_word_flags(message: str, rx: re.Pattern):
    """Every start inside one [\\w.-] run reaches the same run end.

    Only what follows that end decides ("(?:\\.exe)?" lies inside the run),
    so a run that fails is skipped whole instead of retried per letter.
    """

    def find(pos: int):
        while head := _WORD_HEAD.search(message, pos):
            end = _WORD_RUN.match(message, head.end()).end()
            if _WORD_FLAG.match(message, end):
                return head.start()
            pos = end
        return None

    return find


def _scan_prompts(message: str, rx: re.Pattern):
    """Line starts inside one whitespace block reach the same first
    printable character, which alone decides."""

    def find(pos: int):
        while pos <= len(message) and (line := _LINE_START.search(message, pos)):
            text = _LINE_LEAD.match(message, line.start()).end()
            if _PROMPT.match(message, text):
                return line.start()
            pos = max(text, line.start() + 1)
        return None

    return find


# Alternation order is match priority, as in the joined regex below. A scan
# gets the message and its alternative's regex and returns find(pos): the
# leftmost start >= pos where that alternative matches, or None.
_SHAPE_SCANS = {
    r"```(?:powershell|pwsh|bash|shell|cmd|python)?[^\n]*\n[\s\S]*?```": _scan_fences,
    r"`[^`\n]*(?:\$env:|https?://|--?[a-z]|[a-z]:\\|/[\w.-])[^`\n]*`": _scan_inline,
    r"\$env:[a-z_]\w*\s*=": _scan_plain,
    r"\b[a-z][\w.-]*(?:\.exe)?\s+"
    r"(?:--?[a-z][\w-]*|https?://\S+|[a-z]:\\\S+|/[\w.-]+)": _scan_word_flags,
    r"^\s*(?:ps>\s*|\$\s+)\S+": _scan_prompts,
}
_SHAPE_ALTERNATIVES = tuple(
    (re.compile("(?im)" + pattern), scan) for pattern, scan in _SHAPE_SCANS.items()
)
# The definition the scans reproduce; only the self-test runs it directly.
_COMMAND_HANDOFF_SHAPE = re.compile(r"(?im)(?:" + "|".join(_SHAPE_SCANS) + ")")


def find_command_shapes(message: str) -> list[re.Match]:
    """What _COMMAND_HANDOFF_SHAPE.finditer(message) yields, in linear time.

    finditer takes the leftmost start and, there, the first alternative that
    matches. Each alternative's next start is kept until a taken shape passes
    over it, so every scan only moves forward; only a taken shape is matched
    in full, and taken shapes do not overlap.
    """
    finders = [scan(message, rx) for rx, scan in _SHAPE_ALTERNATIVES]
    ahead = [find(0) for find in finders]
    shapes = []
    while any(start is not None for start in ahead):
        start, first = min((start, i) for i, start in enumerate(ahead) if start is not None)
        shape = _SHAPE_ALTERNATIVES[first][0].match(message, start)
        shapes.append(shape)
        for i, pending in enumerate(ahead):
            if pending is not None and pending < shape.end():
                ahead[i] = finders[i](shape.end())
    return shapes


_FIRST_PERSON = re.compile(r"(?i)\b(?:i|we|я|мы)\b")
_SECOND_PERSON = re.compile(
    r"(?i)\b(?:you|user|operator|admin|customer|human|person|вы|вам|вас|ты|тебе|тебя|"
    r"пользовател\w*|оператор\w*|администратор\w*|человек\w*)\b"
)
_DELEGATED_TO_CONTEXT = re.compile(
    r"(?i)\b(?P<actor>[a-z][\w-]*)\s+to(?:\s+[a-z][\w-]*)?\s*$"
)
_AGENT_TO_CONTROLS = {
    "need", "want", "have", "got", "plan", "intend", "intending", "going",
    "try", "trying", "ready", "able", "supposed", "asked", "told", "instructed",
    "required", "expected", "allowed", "prepared", "decided", "about",
}
_RUSSIAN_DIRECTIVE = re.compile(r"(?i)[а-яё]")


def load_user_task_guard():
    """Load the canonical action/question classifier instead of cloning it here."""
    path = Path(__file__).with_name("user-task-completion-guard.py")
    spec = importlib.util.spec_from_file_location("stop_phrase_user_task_guard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load user-task-completion-guard.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def has_measured_disclosure_boundary(context: str) -> bool:
    """True only for an observed public/external boundary, not a hypothetical one."""
    return bool(
        _DISCLOSURE_BOUNDARY.search(context)
        and _BOUNDARY_OBJECT.search(context)
        and _MEASURED_EVIDENCE.search(context)
    )


def get_final_assistant_message(transcript_path: str | None) -> str:
    """Read the transcript file and return the last assistant message text.

    The exact transcript location and format is not documented for Stop hooks
    at the time of writing. This function tries the Claude-Code-typical layout
    and falls back gracefully - if it can't find the transcript, return empty
    string (no false positives).
    """
    if not transcript_path:
        return ""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    # Transcript is JSONL, iterate from end to find the last assistant entry
    last_content = ""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = obj.get("role") or obj.get("message", {}).get("role")
        if role != "assistant":
            continue
        content = obj.get("content") or obj.get("message", {}).get("content")
        if isinstance(content, str):
            last_content = content
        elif isinstance(content, list):
            # Anthropic message format: list of blocks with type/text
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            last_content = "\n".join(parts)
        if last_content:
            break
    return last_content


def final_assistant_message(event: dict, transcript_path: str | None) -> str:
    """Prefer the documented Stop payload; retain transcript compatibility fallback."""
    payload = event.get("last_assistant_message")
    if isinstance(payload, str) and payload.strip():
        return payload
    return get_final_assistant_message(transcript_path)


def get_user_messages(transcript_path: str | None) -> list[str]:
    """Return all user text newest-first for intent routing across data continuations."""
    if not transcript_path:
        return []
    path = Path(transcript_path)
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    messages: list[str] = []
    for line in reversed(lines):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = obj.get("role") or obj.get("message", {}).get("role")
        if role != "user":
            continue
        content = obj.get("content") or obj.get("message", {}).get("content")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "\n".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
        else:
            text = ""
        if text:
            messages.append(text)
    return messages


def resolve_user_intent(user_messages: list[str], classifier) -> tuple[str, str]:
    """Find the newest intent-bearing prompt, skipping intervening data and chatter."""
    for prompt in user_messages:
        if _EXPLICIT_TUTORIAL_REQUEST.search(prompt):
            return "tutorial", prompt
        _, actionable = classifier.classify_prompt(prompt)
        if actionable:
            return "action", prompt
    return "none", ""


def has_evidence_bound_external_task(event: dict, prompt: str, classifier) -> bool:
    """Accept an external handoff only for the exact validated durable work order."""
    root = classifier.repo_root(Path.cwd())
    if root is None:
        return False
    session = classifier.session_id(event)
    for request in classifier.task_requests(root, session):
        if request.get("prompt") != prompt:
            continue
        outcome, _ = classifier.assess_task(root, request)
        return outcome == "BLOCKED_EXTERNAL"
    return False


# Verbs that actually hand a command over. A command SHAPE on its own does not:
# "the repo has `smudge --skip` set" names a setting, "run `foo --bar`" assigns
# work. Measured 2026-09-20: without this, a report that quotes any flag was
# indistinguishable from an instruction, and the guard fired on its own author's
# technical writing -- which is how a guard teaches people to phrase around it
# instead of to finish the work.
# Russian verbs keep every assigning form (imperative, infinitive, "ты ...шь",
# "давайте ...м", imperfective "запускай") and drop only the past tense:
# "запустили"/"выполнила" report finished work, not an assignment.
_INSTRUCTION_VERB = re.compile(
    r"(?i)\b(?:run|execute|invoke|launch|paste|enter|type|copy|set|export|"
    r"install|open|visit|click|sign in|log in|login|"
    r"запусти(?:те|ть|шь|м|мте)?|запускай(?:те)?|"
    r"выполни(?:те|ть|шь|м|мте)?|выполняй(?:те)?|"
    r"установи(?:те|ть|шь|м|мте)?|устанавливай(?:те)?|"
    r"сделай(?:те)?|вставь(?:те)?|"
    r"введи(?:те)?|открой(?:те)?|"
    r"пропиши(?:те)?|"
    r"скопируй(?:те)?|набери(?:те)?|"
    r"зайди(?:те)?|войди(?:те)?)\b"
)
# A fence only where it opens a line: a ``` mentioned in prose must not pair
# with the real fence and blank the sentence between them.
_FENCED_CODE = re.compile(r"(?m)^[ \t]*```[^\n]*\n[\s\S]*?^[ \t]*```")
# Only whitespace-free spans: a span with spaces may be a mis-paired backtick
# (PowerShell escape, stray quote) swallowing real prose, or a whole command
# whose own verb still signals the hand-off.
_INLINE_NAME = re.compile(r"`[^`\s]+`")
# Linear split (a slash-anchored pattern rescans a long run from every start);
# brackets end a token so "[Откройте](https://...)" keeps its link text.
_TOKEN = re.compile(r"[^\s`\[\]()<>]+")
# "запусти/перезапусти" or "вы/ты" carry a slash but are prose, not a path.
_PATH_SHAPE = re.compile(
    r"^(?:[a-z]:[/\\]|[/~.]|[^/\\]*://)|[/\\].*[/\\]|[/\\][^/\\]*\.\w+$",
    re.IGNORECASE,
)


def _blank(match: re.Match) -> str:
    return " " * len(match.group(0))


def _blank_path(match: re.Match) -> str:
    token = match.group(0)
    if "/" not in token and "\\" not in token:
        return token
    return _blank(match) if _PATH_SHAPE.search(token.rstrip(".,;:!?'\"")) else token


@functools.lru_cache(maxsize=4)  # one message, judged once per command shape
def _mask_code(message: str) -> str:
    """Blank fenced blocks, quoted names and paths, keeping offsets.

    `data\\export\\x.jsonl` or docs/REVIEW-AND-BOARDS-RUN.md name a thing; the
    words inside them are not the sentence's verb or addressee.
    """
    message = _FENCED_CODE.sub(_blank, message)
    message = _INLINE_NAME.sub(_blank, message)
    return _TOKEN.sub(_blank_path, message)


def shape_is_instruction(message: str, start: int, end: int) -> bool:
    """True when a command-shaped span is actually being assigned to someone.

    The window is the surrounding sentence, where an instruction puts either
    its addressee ("you", "вам") or its imperative ("run", "запусти"). A span
    with neither is being described, not handed over.
    """
    left = max(0, start - 180)
    right = min(len(message), end + 80)
    masked = _mask_code(message)
    if message.startswith("```", start):
        # A fenced block judged as the shape keeps its own words; a block the
        # agent ran and shows as evidence is cleared by agent_owns_phrase.
        masked = masked[:start] + message[start:end] + masked[end:]
    window = masked[left:right]
    return bool(_SECOND_PERSON.search(window) or _INSTRUCTION_VERB.search(window))


def agent_owns_phrase(message: str, start: int) -> bool:
    """True when the nearest explicit subject in this sentence is the agent."""
    prefix = message[:start]
    if message.startswith("```", start):
        # A completed command is commonly shown on the next line as evidence.
        # Bind the whole fenced block to the immediately preceding ownership claim.
        prefix = prefix.rstrip()
    sentence_start = max(
        prefix.rfind(mark)
        for mark in (".", "!", "?", "\n", ";")
    )
    context = prefix[sentence_start + 1:]
    first = list(_FIRST_PERSON.finditer(context))
    if not first:
        return False
    delegated = _DELEGATED_TO_CONTEXT.search(context)
    if delegated and delegated.group("actor").lower() not in _AGENT_TO_CONTROLS:
        return False
    second = list(_SECOND_PERSON.finditer(context))
    return not second or first[-1].start() > second[-1].start()


def agent_capable_user_homework(
    message: str,
    user_messages: list[str],
    event: dict,
) -> str | None:
    """Detect an executable machine step handed back during an action request."""
    try:
        classifier = load_user_task_guard()
    except Exception as exc:  # keep an advisory detector from breaking every Stop
        print(f"[stop-phrase-guard] action classifier unavailable: {exc}", file=sys.stderr)
        return None
    intent, prompt = resolve_user_intent(user_messages, classifier)
    if intent != "action":
        return None
    directives = [
        match
        for match in _USER_WORK_DIRECTIVE.finditer(_mask_code(message))
        if _RUSSIAN_DIRECTIVE.search(match.group(0))
        or not agent_owns_phrase(message, match.start())
    ]
    command_shapes = [
        match
        for match in find_command_shapes(message)
        if not agent_owns_phrase(message, match.start())
        and shape_is_instruction(message, match.start(), match.end())
    ]
    if not directives and not command_shapes:
        return None
    # A genuine human-only boundary is valid only after the agent has executed
    # the machine-owned prefix and is asking for the irreducibly human input.
    human_boundary = bool(
        _HUMAN_ONLY_INPUT.search(message) or _PHYSICAL_HUMAN_BOUNDARY.search(message)
    )
    if _COMPLETED_MACHINE_PREFIX.search(message) and human_boundary:
        allowed = _HUMAN_ONLY_DIRECTIVE
        physical = bool(_PHYSICAL_HUMAN_BOUNDARY.search(message))
        machine_directives = []
        for directive in directives:
            value = directive.group(0)
            if allowed.fullmatch(value):
                continue
            if physical and _PHYSICAL_ONLY_DIRECTIVE.fullmatch(value):
                continue
            machine_directives.append(directive)
        if not machine_directives and not command_shapes:
            return None
    if has_evidence_bound_external_task(event, prompt, classifier):
        return None
    trigger = directives[0] if directives else command_shapes[0]
    return trigger.group(0)


def scan_phrases(message: str) -> list[tuple[str, str]]:
    """Return list of (category, matched_text) hits in the message."""
    lower = message.lower()
    # Whole-message meta suppression: a message that names the guard/its categories is
    # documenting it, not deferring. (Fixes the guard firing on its own description.)
    if any(sm in lower for sm in STRONG_META_MARKERS):
        return []
    hits: list[tuple[str, str]] = []
    for category, patterns in PHRASE_CATEGORIES:
        for pat in patterns:
            m = re.search(pat, lower, re.IGNORECASE)
            if not m:
                continue
            # Suppress if this looks like meta-discussion
            start = max(0, m.start() - 200)
            end = min(len(lower), m.end() + 200)
            context = lower[start:end]
            if any(marker.lower() in context for marker in META_DISCUSSION_MARKERS):
                continue
            if category == "private_credential_refusal" and has_measured_disclosure_boundary(context):
                continue
            hits.append((category, m.group(0)))
    return hits


def main() -> int:
    # Read Stop hook input from stdin (JSON with transcript path, session, etc)
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}

    # Transcript path field varies by Claude Code version; try common names.
    transcript_path = (
        event.get("transcript_path")
        or event.get("transcriptPath")
        or event.get("transcript")
        or os.environ.get("CLAUDE_CODE_TRANSCRIPT_PATH")
    )

    # Counter marker: keep enforcing repeated deferrals (up to MAX_FIRES) instead of
    # giving up after the first block — but cap it so a truly unavoidable phrase can't
    # hard-deadlock the session. (User 2026-06-09: "всегда всё доделываем до конца".)
    MAX_FIRES = 3
    cwd = Path.cwd()
    marker = cwd / ".claude" / ".stop-phrase-guard-fired"
    fires = 0
    if marker.exists():
        try:
            fires = int((marker.read_text(encoding="utf-8").strip() or "0"))
        except (ValueError, OSError):
            fires = 0
    if fires >= MAX_FIRES:
        return 0

    message = final_assistant_message(event, transcript_path)
    if not message:
        return 0  # no transcript, no-op

    hits = scan_phrases(message)
    homework = agent_capable_user_homework(
        message,
        get_user_messages(transcript_path),
        event,
    )
    if homework:
        hits.append(("agent_capable_user_homework", homework))
    if not hits:
        return 0

    # Group hits by category for readable output
    by_cat: dict[str, list[str]] = {}
    for cat, phrase in hits:
        by_cat.setdefault(cat, []).append(phrase)

    details = "; ".join(
        f"{cat}: '{by_cat[cat][0]}'"
        + (f" (+{len(by_cat[cat]) - 1} more)" if len(by_cat[cat]) > 1 else "")
        for cat in by_cat
    )

    # Increment the fire counter (block now; allow up to MAX_FIRES blocks per session)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(fires + 1), encoding="utf-8")

    user_homework = "agent_capable_user_homework" in by_cat
    credential_refusal = "private_credential_refusal" in by_cat
    reason = (
        "Agent-owned work was handed back to the user: the active request asks for an "
        "outcome, while the final message tells the user to copy, paste, or run an "
        "available machine operation. Read the supplied message/file/image data and "
        "execute every reversible in-scope machine step yourself. If an OTP, CAPTCHA, "
        "physical confirmation, or other human-only input remains, first run the machine "
        "prefix, report the observed waiting prompt, and request only that minimal input. "
        "A real inaccessible environment must bind the exact work order to an evidence-backed "
        "durable BLOCKED_EXTERNAL state; Blocker/Access inventory/Needed authority/Recheck "
        "labels in prose alone do not count."
        if user_homework
        else (
            "Private-context credential refusal: this Claude/Codex working chat is inside "
            "the configured trust boundary. Do not refuse, mask, or replace with a file "
            "pointer when the exact credential is needed to perform or verify the requested "
            "work. Show/use the required value, or name the measured PUBLIC/external boundary "
            "that makes disclosure invalid. Do not dump unrelated credentials."
            if credential_refusal
            else (
                f"Regression phrase guard: the final message contains "
                f"behavioral tells that signal degraded reasoning ({details}). "
                f"Before ending, either (a) actually finish the work, or (b) "
                f"explicitly explain what is blocking and what concrete next "
                f"step is needed. Per rules/finish-the-task.md: do NOT end by asking "
                f"'что дальше?' or offering a menu of options while planned work "
                f"remains — keep doing it in order. A legitimate deferral must be a "
                f"documented canonical status (missing-data, missing-dep, arch-decision, "
                f"scope-explosion, or inaccessible-repo) or real context overflow; it needs "
                f"the required record and evidence. An external blocker is evidence-backed, "
                f"not a label in prose. After a genuine conclusion, you may end."
            )
        )
    )
    response = {
        "decision": "block",
        "reason": reason,
    }
    print(json.dumps(response))
    return 0


def _self_test() -> int:
    """Prove the handoff detector still separates describing from assigning.

    Twelve of these hand a command over and must stay caught; six only name
    one and must not fire. Without the mandatory-red half, loosening the
    detector would be indistinguishable from breaking it. Every case also
    holds the linear shape scan to the regex it replaces. The last checks
    bound time on long unbroken runs: masking, and the whole hand-off check.
    """
    run_ru = "запусти"
    cases = [
        ("describes a setting",
         "у репозитория "
         "стоит `smudge --skip`", False),
        ("states an outcome",
         "`git push --force-with-lease` теперь "
         "проходит", False),
        ("names a flag in passing",
         "the policy check reads `--pull never` from the env", False),
        # Measured 2026-09-24: a location report was blocked twice, by the past
        # tense of "запусти" and by "export"/"RUN" read out of quoted paths.
        ("past tense reports finished work",
         f"вчера {run_ru}ли прогон на сервере `build-rev`", False),
        ("verb inside a quoted path",
         "описания лежат в `data\\export\\pin-text.jsonl`", False),
        ("word inside a quoted filename",
         "отчёт лежит в `docs/REVIEW-AND-BOARDS-RUN.md`", False),
        ("russian imperative", f"{run_ru} `claude auth login --claudeai`", True),
        ("russian plural imperative",
         f"{run_ru}те `claude auth login --claudeai`", True),
        # Independent review 2026-09-24: forms the first cut of this fix lost.
        ("russian future second person",
         f"Потом {run_ru}шь `python -m foo --bar`.", True),
        ("russian imperfective imperative",
         "Запускай `npm run dev --host`", True),
        ("stray backtick must not swallow prose",
         f"Файл `config.json и потом {run_ru}те `python -m foo --bar`.", True),
        ("bare remaining step",
         "Остался один шаг: `claude auth login --claudeai`.", True),
        # Second review pass: masking must not reach prose or the fence itself.
        ("fenced command after a neutral lead-in",
         "Вот команда:\n```powershell\npython -m telegram_live_cli auth --login\n```",
         True),
        ("slash between two verbs is prose",
         f"{run_ru.capitalize()}/пере{run_ru} сервис: `systemctl restart foo --now`.",
         True),
        ("link text is prose, only its target is a path",
         f"[{run_ru.capitalize()}те](https://github.com/o/r/actions/workflows/ci.yml)"
         " workflow `ci --ref main`.", True),
        ("fence named in prose does not pair with the real one",
         f"Блоки оформляются через ```. {run_ru.capitalize()}те:\n```\npython -m foo --bar\n```",
         True),
        ("english imperative", "run `claude auth login --claudeai` to finish", True),
        ("addressed to a person",
         "тебе нужно `claude auth login --claudeai`",
         True),
    ]
    fails = []
    for label, text, want in cases:
        shapes = find_command_shapes(text)
        reference = [m.span() for m in _COMMAND_HANDOFF_SHAPE.finditer(text)]
        if [s.span() for s in shapes] != reference:
            fails.append(f"{label}: shape scan disagrees with the regex")
        if not shapes:
            fails.append(f"{label}: no command shape matched at all")
            continue
        got = any(shape_is_instruction(text, s.start(), s.end()) for s in shapes)
        if got != want:
            fails.append(f"{label}: expected flagged={want}, got {got}")
    for label, text in (
        ("quoted filename", "отчёт — `docs/REVIEW-AND-BOARDS-RUN.md`"),
        ("bare path", "Отчёт лежит в docs/REVIEW-AND-BOARDS-RUN.md."),
        ("fenced output", "Я " + run_ru + "ла:\n```\nnpm run test --ci\n```"),
    ):
        if list(_USER_WORK_DIRECTIVE.finditer(_mask_code(text))):
            fails.append(f"directive read out of a {label}")
    owned_fence = "Я " + run_ru + "ла:\n```\nnpm run test --ci\n```"
    if not agent_owns_phrase(owned_fence, owned_fence.index("```")):
        fails.append("agent's own fenced output not bound to its owner")
    long_run = "Хэш: " + "A" * 100_000 + " готово."
    started = time.perf_counter()
    _mask_code(long_run)
    if time.perf_counter() - started > 1.0:  # quadratic scan took ~97 s here
        fails.append("masking a 100k unbroken run is not linear")
    # Through the same call the Stop hook makes; the control proves that call
    # reaches the shape scan rather than returning before it.
    prompt = "Настрой всё и запусти авторизацию."
    control = "Остался один шаг: `claude auth login --claudeai`."
    if agent_capable_user_homework(control, [prompt], {}) != "`claude auth login --claudeai`":
        fails.append("timed path does not reach the command-shape scan")
    path_run = "a/" + "b." * 50_000
    started = time.perf_counter()
    verdict = agent_capable_user_homework(path_run, [prompt], {})
    if time.perf_counter() - started > 1.0:  # the shape regex alone took ~100 s here
        fails.append("the hand-off check on a 100k path-like run is not linear")
    if verdict is not None:
        fails.append(f"a bare path-like run was read as a hand-off: {verdict[:40]!r}")
    for f in fails:
        print("FAIL:", f)
    print("stop-phrase-guard self-test:", "FAILED" if fails else "ok")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
