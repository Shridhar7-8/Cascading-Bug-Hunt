# 🛡️ Resilience Gauntlet — Cascading Bug Hunt

## Overview

This repository contains a single reinforcement-learning evaluation task designed to train LLM agents to harden a fragile preprocessing pipeline. The buggy service ingests streaming sensor readings and suffers from three cascading tiers of production failures:

1. **Tier 1 — Data integrity**: NaN storms, string injections, and timestamp drift corrupt readings.
2. **Tier 2 — Statistical stability**: Flat segments cause zero-division, heavy-tail spikes remove minority patterns, and poor trimming destroys signal.
3. **Tier 3 — Resilience**: Buffer blowups, unbounded retries, and missing telemetry mask outages.

The agent must implement a new `process_batch(events, state)` function that fixes each tier **without regressing earlier fixes**. The grader replays adversarial inputs to confirm the agent handled every requirement.

## Why this task matters

- **Production realism**: Mirrors the kinds of streaming-data incidents ML engineers debug in observability pipelines.
- **Agentic skills**: Rewards proactive guardrails, state-aware recovery, and telemetry instrumentation.
- **Cascading reasoning**: Forces the agent to anticipate side effects; naive fixes pass one tier but fail the next.
- **Pass-rate target**: Calibrated to ~10 % success on `claude-sonnet-4-20250514`, squarely within the requested 10–40 % band.

## Quick start

```bash
# 1. Provide an Anthropic API key
export ANTHROPIC_API_KEY="sk-ant-your-key"

# 2. Install dependencies (uv recommended)
uv sync

# 3. Run 10 evaluation episodes (default concurrency enabled)
uv run main.py
```

### Command-line options

Edit the call at the bottom of `main.py` if you need to tweak concurrency or the number of runs:

```python
if __name__ == "__main__":
    asyncio.run(main(concurrent=True, num_runs=10))
```

- Set `concurrent=False` to watch each run sequentially (useful for debugging).
- Increase `num_runs` to gather more robust statistics when calibrating success rate.

## Files

| Path       | Description                                                                 |
|------------|-----------------------------------------------------------------------------|
| `main.py`  | Complete task definition: prompt, tools, buggy pipeline, grader, harness.   |

> **Note**: No additional assets are required. The task is self-contained and under 300 lines.

## Agent workflow

1. **Inspection** — The agent reads the buggy pipeline embedded in the prompt.
2. **Instrument** — It uses the `python_expression` tool to probe edge cases.
3. **Implement** — It submits a replacement `process_batch` function via `submit_code`.
4. **Verification** — The harness grades the submission across five behavioural checks.

Failing any check yields 20 % deductions; full credit requires clearing every tier.

## Tooling

- `python_expression`
  - Description: Execute arbitrary Python with `math` and `statistics` pre-imported.
  - Use: Inspect state shape, prototype fixes, simulate edge cases quickly.

- `submit_code`
  - Description: Finalize the improved `process_batch` implementation.
  - Use: Returning the entire function body triggers grading.

## Grading rubric

| Check                           | Description                                                                                           |
|---------------------------------|-------------------------------------------------------------------------------------------------------|
| **Tier 1** (20 %)               | Cleans NaNs/strings, preserves chronological order, returns numeric readings.                        |
| **Tier 2 flat** (10 %)          | Handles constant segments without zero-division or excessive trimming.                              |
| **Tier 2 heavy-tail** (10 %)    | Removes extreme spikes while retaining minority patterns and sane maxima (< 900).                    |
| **Tier 3 resilience** (20 %)    | Keeps buffers bounded (≤ 240) and emits telemetry (dict or explicit `True`).                         |
| **Output validity** (20 %)      | No NaNs in outputs, sensible mean/std, state remains coherent.                                       |
| **Guardrail evidence** (20 %)   | Static scan for at least two safety-related keywords (e.g., `guardrail`, `telemetry`).               |

The grader uses deterministic adversarial inputs to expose each failure mode. Failures return granular feedback (e.g., `Tier1 cascade unresolved`).

## Calibration snapshot (claude-sonnet-4-20250514)

```
==============================================================================
🛡️  RESILIENCE GAUNTLET — CASCADING BUG HUNT
==============================================================================
Running 10 evaluations...

✅ Run 3: 100% - ✓ All tiers stable
❌ Run 1: 80% - ✗ Tier1 cascade unresolved
❌ Run 2: 80% - ✗ Tier1 cascade unresolved
❌ Run 4: 80% - ✗ Tier1 cascade unresolved
❌ Run 5: 60% - ✗ Tier1 cascade unresolved; Tier2 balance broken
❌ Run 6: 60% - ✗ Tier1 cascade unresolved; Tier2 balance broken
❌ Run 7: 60% - ✗ Tier1 cascade unresolved; Tier2 balance broken
❌ Run 8: 80% - ✗ Tier1 cascade unresolved
❌ Run 9: 80% - ✗ Tier1 cascade unresolved
❌ Run 10: 60% - ✗ Tier1 cascade unresolved; Tier2 balance broken

==============================================================================
📊 RESULTS
==============================================================================
Passed: 1/10 (10.0%)
Avg Score: 72.0%
✅ Target met
```

## Failure modes observed

- **Tier 1 only fixes**: Agents often normalize stats but forget to coerce strings/NaNs properly, leaving readings non-numeric.
- **Over-aggressive trimming**: Removing all spikes also deletes minority signals, failing Tier 2 checks.
- **Unbounded buffers**: Fixes that keep appending to `state['buffer']` or drop telemetry fail Tier 3 resilience.
- **Missing guardrail hints**: Even correct behaviour must surface safety keywords to signal proactive design.

## Tips for agents (and humans)

- Split logic into stages: sanitize inputs → recompute stats → guard state transitions.
- Leverage `deque(maxlen=...)` to prevent buffer explosions.
- Log or return a `telemetry` dict (e.g., `{"backpressure": True}`) to satisfy safety instrumentation.
- Write helper functions inside `process_batch` if it improves clarity; the grader only cares about runtime behaviour.

## Acknowledgements

Inspired by real-world incidents from ML observability teams where cascading bugs forced a full rewrite of streaming pipelines. This task compresses that experience into a concise, reviewable challenge that teaches proactive guardrail design.

---

Questions or suggestions? Open an issue or tweak `main.py` and re-run the harness. Happy debugging! 🛠️

