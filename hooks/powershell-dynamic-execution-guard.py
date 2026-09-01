#!/usr/bin/env python3
"""PreToolUse: reject dynamic text execution in PowerShell.

This is deliberately narrower than a ban on PowerShell.  Static commands and
static script blocks are normal administration; the injection boundary appears
when untrusted or dynamically-built text is handed to an evaluator:

  iex $env:PAYLOAD
  pwsh -EncodedCommand $payload
  powershell -File $env:SCRIPT_PATH
  & ([scriptblock]::Create((Get-Content payload.ps1 -Raw)))

The guard accepts static literals (including a literal encoded command) and a
same-command literal variable assignment.  It does not decide whether a
PowerShell command is otherwise safe; destructive-command and approval guards
remain responsible for those independent policies.  There is deliberately no
model-controlled bypass: this hook guards precisely the boundary where a model
can turn data into code.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from safety_common import (  # noqa: E402
    allow,
    bash_command,
    block,
    executable_text,
    log,
    read_event,
)

_POWERSHELL_HOST = re.compile(r"(?i)(?:^|[;&|]\s*)(?:powershell|pwsh)(?:\.exe)?\b")
_INVOKE_EXPRESSION = re.compile(r"(?i)\b(?:invoke-expression|iex)\b")
_ENCODED_COMMAND = re.compile(r"(?i)(?:^|\s)-(?:encodedcommand|enc)\s*(?::|\s)\s*(?P<arg>[^\s;|]+)")
_COMMAND_PARAMETER = re.compile(r"(?i)(?:^|\s)-(?:command|c)\s*(?::|\s)\s*(?P<arg>[^\s;|]+)")
_FILE_PARAMETER = re.compile(r"(?i)(?:^|\s)-(?:file|f)\s*(?::|\s)\s*(?P<arg>[^\s;|]+)")
_CALL_OPERATOR = re.compile(r"(?m)(?:^|[;|]\s*)&\s*(?P<arg>[^;|\r\n]+)")
_SCRIPTBLOCK_PARAMETER = re.compile(
    r"(?i)\binvoke-command\b[^\r\n;|]*\s-scriptblock\s+(?P<arg>[^;|\r\n]+)"
)
_DYNAMIC_SOURCE = re.compile(
    r"(?ix)"
    r"\$\s*\{?\s*(?:env:|global:|script:|using:|input\b|args\b|psboundparameters\b|"
    r"_\b|executioncontext\b|variable:)"
    r"|\$\("
    r"|\b(?:get-content|gc|invoke-webrequest|iwr|invoke-restmethod|irm|curl|wget|"
    r"receive-job|import-clixml|convertfrom-json|read-host|get-variable|gv)\b"
)
_VARIABLE = re.compile(r"^\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b")
_LITERAL_ASSIGNMENT = re.compile(
    r"(?ims)(?:^|[;\r\n])\s*\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<quote>['\"])(?P<value>(?:.(?!\2))*.)?\2"
)


def _literal_variables(command: str) -> set[str]:
    """Return variables assigned a single quoted literal in this command.

    This intentionally recognizes only the unambiguous local form.  A value
    calculated through concatenation, command substitution, a file, the
    environment, or another variable remains dynamic.
    """
    names: set[str] = set()
    for match in _LITERAL_ASSIGNMENT.finditer(command):
        names.add(match.group("name").lower())
    return names


def _is_dynamic(argument: str, literal_variables: set[str]) -> bool:
    """True when an execution sink receives dynamic rather than literal text."""
    value = argument.strip()
    if not value:
        return False
    variable = _VARIABLE.match(value)
    if variable and variable.group("name").lower() in literal_variables:
        return False
    return bool(_DYNAMIC_SOURCE.search(value) or variable)


def find_dynamic_execution(command: str) -> str | None:
    """Return a concise matching sink, or ``None`` for static/non-PS input."""
    # Do not trip on an echo/search/documentation string that only *names* an
    # unsafe construct.  executable_text retains a payload when a downstream
    # interpreter can receive it, so `Write-Output ... | iex` still blocks.
    executable = executable_text(command)
    if not executable or not (_POWERSHELL_HOST.search(executable) or
                              _INVOKE_EXPRESSION.search(executable) or
                              _CALL_OPERATOR.search(executable) or
                              _SCRIPTBLOCK_PARAMETER.search(executable)):
        return None

    literals = _literal_variables(executable)

    for encoded in _ENCODED_COMMAND.finditer(executable):
        if _is_dynamic(encoded.group("arg"), literals):
            return f"encoded-command <- {encoded.group('arg')[:96]}"

    for command_parameter in _COMMAND_PARAMETER.finditer(executable):
        if _is_dynamic(command_parameter.group("arg"), literals):
            return f"command <- {command_parameter.group('arg')[:96]}"

    for file_parameter in _FILE_PARAMETER.finditer(executable):
        if _is_dynamic(file_parameter.group("arg"), literals):
            return f"file <- {file_parameter.group('arg')[:96]}"

    for invocation in _INVOKE_EXPRESSION.finditer(executable):
        remainder = executable[invocation.end():].lstrip()
        # A pipeline into IEX is dynamic even if the command has no explicit
        # argument.  IEX consumes the upstream objects as its command text.
        before = executable[:invocation.start()]
        if re.search(r"\|\s*$", before):
            return "Invoke-Expression <- pipeline input"
        if _is_dynamic(remainder, literals):
            return f"Invoke-Expression <- {remainder[:96]}"

    for scriptblock in _SCRIPTBLOCK_PARAMETER.finditer(executable):
        argument = scriptblock.group("arg")
        if _is_dynamic(argument, literals):
            return f"Invoke-Command -ScriptBlock <- {argument[:96]}"

    for call in _CALL_OPERATOR.finditer(executable):
        argument = call.group("arg")
        if _is_dynamic(argument, literals):
            return f"call-operator <- {argument[:96]}"
        # ScriptBlock::Create is only static when its argument is a literal.
        if re.search(r"(?i)\[scriptblock\]::create\s*\(", argument):
            create_arg = argument.split("(", 1)[1]
            if _is_dynamic(create_arg, literals):
                return f"scriptblock-create <- {create_arg[:96]}"

    return None


def main() -> None:
    event = read_event()
    tool_name = str(event.get("tool_name", ""))
    if tool_name not in {"Bash", "PowerShell"}:
        allow()
    command = bash_command(event.get("tool_input", {}))
    if not command:
        allow()
    finding = find_dynamic_execution(command)
    if not finding:
        allow()
    log("BLOCK", "powershell_dynamic_execution_guard", "deny_dynamic_execution", finding, command)
    block(
        "Dynamic PowerShell text execution is blocked:\n"
        f"  {finding}\n"
        "The command crosses dynamic/untrusted text into an evaluator. Pass a typed "
        "value to a narrow tool or validate a fixed allowlisted value first; do not use "
        "Invoke-Expression, -EncodedCommand, dynamic -File, &, or -ScriptBlock as a text bridge.\n"
        "A known static literal is allowed. This evaluator boundary has no command-text "
        "or environment-variable bypass."
    )


if __name__ == "__main__":
    main()
