# A launch is a promise to look at it

Question: when something long is started — training, a scrape, a batch — what makes the
agent actually go back and confirm it is running, computing, and not quietly dead?

## The failure is silent by construction

A job that died in its first second looks exactly like a job running quietly. Every
available tell points the wrong way:

- **no output** can mean progress (buffered stdout) or a dead process;
- **an empty log** can mean the writer never opened it;
- **no answer over ssh** can mean the box is busy, or the link is flaky, or the machine
  is gone — this one is the worst, because absence of evidence arrives looking identical
  to evidence of absence.

So "did it fail?" cannot be answered by waiting. It has to be asked.

## Three different questions, and only one is liveness

"Is training running" decomposes, and the parts fail independently:

| Question | What proves it | What passes it while broken |
|---|---|---|
| Does the process exist? | `pgrep`, `docker ps`, `Get-Process` | a process alive and doing nothing |
| Is work advancing? | log growing, step counter moving, GPU busy | a hot GPU on a loop that never commits |
| Is output landing? | files appearing, rows written, size increasing | **a full disk** — every earlier check green |

That last row is not hypothetical here: a pipeline that measured green end to end while
the store silently rejected the final write is already a recorded incident on this
machine. A liveness probe answers the first question and is routinely mistaken for an
answer to the third.

## Prior art, and the distinction that matters

Two different things get called a heartbeat:

- a **task watchdog** announces "still working" from inside the job;
- a **scheduled agent heartbeat** wakes the agent to inspect, decide, and possibly act.

Only the second catches a job that stopped announcing because it stopped existing.
https://andrewcrookston.com/articles/close-the-loop.html draws the sharper line inside
that second category: a *generic* heartbeat is a runner that fires on time and lets the
turn proceed regardless, while a *structured* one is a workflow that "refuses to advance
when those preconditions aren't met". Generic catches execution errors; structured
catches orchestration errors — the thing that never got checked at all.

https://github.com/NousResearch/hermes-agent/issues/15400 asks for heartbeat jobs as a
first-class feature for supervised long-running projects; Google's ADK
(https://developers.googleblog.com/build-long-running-ai-agents-that-pause-resume-and-never-lose-context-with-adk/)
solves the adjacent problem of surviving the wait rather than verifying the work.

**This machine already solved the remote half, on 2026-06-28.** Over a link that answered
only in rare windows, foreground probes were useless — so the check went onto the box: a
local scheduled script, WAN-independent, restarting the job if dead, **capped at three
attempts**, writing a `_STUCK` marker and removing itself when the cap was hit, and
self-deleting once epochs appeared. That cap is the same guardrail the Stop-hook loop bug
(https://github.com/anthropics/claude-code/issues/55754) asks for, arrived at independently.

## What was missing, measured

Nothing tied the launch to the check. Over 30 days of this machine's history:

- **2,958 launches** (`nohup`, detached `docker run`, `sbatch`, `schtasks`, plus the
  harness's own `run_in_background`);
- **42 never probed anywhere later in the same session**, across **28 of 175 sessions**;
- at the 30-minute mark, **11.5% unprobed** — the check usually happens, just late enough
  that a dead job has already burned an hour of wall clock.

One session in six ended with something running that nobody had confirmed was running.

## The mechanism

`hooks/launch-watch-guard.py`, wired on `PostToolUse` and `Stop`:

- **PostToolUse** records launches and records probes. A probe naming the launch's own log
  or script clears it; a generic liveness probe (`nvidia-smi`, `docker ps`, `tail`,
  `journalctl`) clears everything before it, because whoever ran it has looked.
- **Stop** refuses to end while a launch from the last 6 hours has no probe after it, and
  names what to check: the process exists, the log is growing, the GPU is busy, the output
  is landing.
- For a **remote** launch it carries the 2026-06-28 finding forward: put the durable check
  on the box, because a foreground probe returning nothing across a flaky link is not
  evidence of anything.

It cannot produce the #55754 loop: the shared stop-budget caps any gate at three refusals,
and one probe clears the watch permanently rather than per-turn.

Detection is deliberately narrow — specific launch verbs plus the structured
`run_in_background` flag, with folder-openers excluded and a trailing `&` explicitly not
counted. Three other guards this week over-matched shell strings and produced hundreds of
false positives before being narrowed; that lesson was applied here first rather than
after.

## What it does not do

- **It does not verify progress, only that someone looked.** The gate is satisfied by a
  probe, and a probe can be glanced at and misread. It converts "nobody checked" into
  "somebody checked", which is the smaller half of the problem.
- **It does not watch after the session ends.** A job outliving the session is exactly the
  case the box-side watchdog exists for, and that still has to be set up per job.
- **It cannot see a job launched by something other than a tool call** — a cron entry, a
  scheduled task created earlier, a job someone else started.
