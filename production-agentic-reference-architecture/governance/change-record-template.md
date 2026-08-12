# Change record — <short title>

One append-only entry per governed change (governance §2.5). Copy this file into
`governance/changes/YYYY-MM-DD-<slug>.md`.

| Field | Value |
|---|---|
| **Date** | YYYY-MM-DD |
| **Author** | |
| **Reviewer** | (must be the named reviewer for this artifact — governance §1) |
| **Class** | Routine / Governed / Emergency |
| **Artifacts touched** | e.g. `models.py::_synthesize`, `MODEL_FOR_TIER["large"]` |

## Why

What problem this solves, and what was observed that made it necessary. If this came from a
production incident, link the trace id.

## What changed

Specifics. For a model change, both pins: `old → new`.

## Gate result

```
python3 eval/harness.py        → PASS / FAIL
python3 eval/mutation_test.py  → PASS / FAIL
dataset hash                   → <hash>
```

If the dataset was re-baselined, record `old hash → new hash` and why cases were added
(cases are added, not edited — governance §2.4).

## Cost impact

Required if routing, model, fan-out width, or context budget changed.

| | before | after |
|---|---|---|
| mean cost/task | | |
| p95 latency | | |
| tasks/month at envelope | | |

## Rollback plan

The specific move that reverts this (governance §4) and how long it takes.

## Follow-ups

Anything deferred, with an owner.
