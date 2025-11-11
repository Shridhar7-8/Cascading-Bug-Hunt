import os
import asyncio
import json
import math
import statistics as stats
from collections import deque
from contextlib import redirect_stdout
from io import StringIO
from typing import Any
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MAX_TOKENS = 3200

BUGGY_PIPELINE = '''
import math, statistics as stats

def process_batch(events, state):
    if state is None:
        state = {}
    state.setdefault("seen", 0)
    state.setdefault("limit", 500)
    state.setdefault("buffer", [])
    readings = [float(e["reading"]) for e in events]
    mean = sum(readings) / len(readings)
    std = stats.pstdev(readings)
    scores = [(x - mean) / std for x in readings]
    clean = [ev for ev, score in zip(events, scores) if abs(score) < state.get("z_cutoff", 3)]
    state["seen"] += len(events)
    if state["seen"] > state["limit"]:
        state["buffer"].extend(clean)
    return {"clean": clean, "mean": mean, "std": std, "alerts": [], "state": state}
'''

def python_tool(expression: str) -> dict:
    try:
        ns = {"math": math, "stats": stats}
        out = StringIO()
        with redirect_stdout(out):
            exec(expression, ns, ns)
        return {"result": out.getvalue() or "Executed", "error": None}
    except Exception as exc:
        return {"result": None, "error": str(exc)}

def submit_tool(code: str) -> dict:
    return {"code": code, "submitted": True}

def _fresh_state() -> dict:
    return {"seen": 0, "limit": 200, "buffer": deque(maxlen=240), "z_cutoff": 3}

def _no_nan(value: Any) -> bool:
    if isinstance(value, float) and math.isnan(value):
        return False
    return True

def grade(code: str) -> dict[str, Any]:
    try:
        ns = {"math": math, "stats": stats}
        exec(code, ns)
        fn = ns.get("process_batch")
        if not callable(fn):
            return {"passed": False, "score": 0.0, "feedback": "process_batch missing"}
        checks: dict[str, bool] = {}
        issues: list[str] = []

        # Tier 1: data integrity
        try:
            tier1 = [
                {"ts": 3, "reading": " NaN", "tag": "sensor"},
                {"ts": 2, "reading": "5.4", "tag": "healthy"},
                {"ts": 1, "reading": None, "tag": "sensor"},
                {"ts": 5, "reading": "bad", "tag": "sensor"},
                {"ts": 4, "reading": "7.2", "tag": "healthy"},
            ]
            res1 = fn(tier1, _fresh_state())
            clean = res1.get("clean", [])
            ok = isinstance(clean, (list, tuple)) and len(clean) >= 2
            if ok:
                numeric = [row for row in clean if isinstance(row, dict) and isinstance(row.get("reading"), (int, float))]
                ordered = [row.get("ts") for row in clean if isinstance(row, dict)]
                ok = len(numeric) >= 2 and ordered == sorted(ordered)
            checks["tier1"] = bool(ok)
        except Exception as exc:
            checks["tier1"] = False
            issues.append(f"Tier1 crash: {str(exc)[:40]}")
        if not checks["tier1"]:
            issues.append("Tier1 cascade unresolved")

        # Tier 2: statistical stability
        ok2 = True
        try:
            flat = [{"ts": i, "reading": 9.0, "tag": "core"} for i in range(6)]
            res_flat = fn(flat, _fresh_state())
            std = res_flat.get("std")
            clean_flat = res_flat.get("clean", [])
            ok2 &= isinstance(clean_flat, list)
            ok2 &= len(clean_flat) >= len(flat) - 1
            ok2 &= isinstance(std, (int, float)) and not math.isnan(std) and std >= 0
        except Exception as exc:
            ok2 = False
            issues.append(f"Tier2 flat crash: {str(exc)[:40]}")
        try:
            heavy = (
                [{"ts": i, "reading": 10.0 + 0.1 * i, "tag": "core"} for i in range(6)]
                + [{"ts": 100 + i, "reading": 1000.0, "tag": "spike"} for i in range(2)]
                + [{"ts": 200 + i, "reading": 9.5, "tag": "minority"} for i in range(2)]
            )
            res_heavy = fn(heavy, _fresh_state())
            clean_heavy = res_heavy.get("clean", [])
            ok2 &= isinstance(clean_heavy, list) and len(clean_heavy) >= 4
            upper = [ev.get("reading", 0) for ev in clean_heavy if isinstance(ev, dict)]
            ok2 &= upper and max(upper) < 900
            minorities = [ev for ev in clean_heavy if isinstance(ev, dict) and ev.get("tag") == "minority"]
            ok2 &= len(minorities) >= 1
        except Exception as exc:
            ok2 = False
            issues.append(f"Tier2 heavy crash: {str(exc)[:40]}")
        if not ok2:
            issues.append("Tier2 balance broken")
        checks["tier2"] = bool(ok2)

        # Tier 3: resilience and state stability
        try:
            flood = [{"ts": i, "reading": float(i % 7), "tag": "stream"} for i in range(60)]
            hot_state = {"seen": 190, "limit": 200, "buffer": deque(({"ts": -k} for k in range(150)), maxlen=260), "z_cutoff": 3}
            res3 = fn(flood, hot_state)
            buf = res3.get("state", {}).get("buffer", [])
            telemetry = res3.get("telemetry", {})
            if isinstance(buf, deque):
                ok3 = len(buf) <= 240
            else:
                ok3 = isinstance(buf, list) and len(buf) <= 240
            if isinstance(telemetry, dict):
                ok3 &= True
            else:
                ok3 &= telemetry in (True,)
        except Exception as exc:
            ok3 = False
            issues.append(f"Tier3 crash: {str(exc)[:40]}")
        if not ok3:
            issues.append("Tier3 resilience missing")
        checks["tier3"] = bool(ok3)

        # Output validity
        validity = True
        try:
            sanity = [{"ts": i, "reading": float(i), "tag": "test"} for i in range(5)]
            res = fn(sanity, _fresh_state())
            for val in (res.get("mean"), res.get("std")):
                validity &= isinstance(val, (int, float)) and _no_nan(val)
            for row in res.get("clean", []):
                validity &= _no_nan(row.get("reading"))
        except Exception as exc:
            validity = False
            issues.append(f"Validity crash: {str(exc)[:40]}")
        if not validity:
            issues.append("Outputs not trustworthy")
        checks["valid"] = bool(validity)

        # Guardrail evidence - simple static check
        code_lower = code.lower()
        keywords = ["guardrail", "telemetry", "monitor", "backpressure", "fallback"]
        guardrails = sum(1 for token in keywords if token in code_lower) >= 2
        if not guardrails:
            issues.append("Guardrail keywords missing")
        checks["patterns"] = guardrails

        score = sum(checks.values()) / len(checks)
        passed = all(checks.values())
        feedback = "✓ All tiers stable" if passed else "✗ " + "; ".join(dict.fromkeys(issues))
        return {"passed": passed, "score": score, "feedback": feedback, "details": checks}
    except Exception as exc:
        return {"passed": False, "score": 0.0, "feedback": f"Harness error: {str(exc)[:80]}"}

async def run_agent(prompt: str, tools: list, handlers: dict, max_steps: int = 18) -> str | None:
    client = AsyncAnthropic()
    messages: list[MessageParam] = [{"role": "user", "content": prompt}]
    submitted = None
    for _ in range(max_steps):
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=MAX_TOKENS,
            tools=tools,
            messages=messages,
        )
        tool_calls = []
        used_tool = False
        for part in response.content:
            if part.type == "tool_use":
                used_tool = True
                name = part.name
                payload = part.input
                handler = handlers.get(name)
                if handler:
                    if name == "python_expression":
                        result = handler(payload.get("expression", ""))
                    else:
                        result = handler(payload.get("code", ""))
                        if name == "submit_code":
                            submitted = result.get("code")
                    tool_calls.append({"type": "tool_result", "tool_use_id": part.id, "content": json.dumps(result)})
        if used_tool:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_calls})
            if submitted:
                return submitted
        else:
            break
    return submitted

async def run_evaluation(run_id: int, prompt: str, tools: list, handlers: dict) -> tuple[int, bool, float]:
    submission = await run_agent(prompt, tools, handlers)
    if not submission:
        print(f"❌ Run {run_id}: no submission")
        return run_id, False, 0.0
    result = grade(submission)
    status = "✅" if result["passed"] else "❌"
    print(f"{status} Run {run_id}: {result['score']:.0%} - {result['feedback'][:90]}")
    return run_id, result["passed"], result["score"]

def build_prompt() -> str:
    return f"""You are the FIXER agent for a production ML preprocessing service with cascading failures. Investigate and harden the pipeline below across THREE tiers of bugs. Every fix must keep previous tiers stable.

```python
{BUGGY_PIPELINE}
```

TIER 1 — Data integrity: handle NaN storms, string injections, timestamp drift. Ensure outputs stay sorted and numeric.
TIER 2 — Statistical stability: avoid zero-division on flat segments, trim heavy-tail spikes without deleting minority patterns.
TIER 3 — Resilience: prevent buffer blowups, add telemetry/backpressure, keep state bounded after retries.

Requirements:
- Proactive guardrails before risky math.
- Preserve good data while dropping corrupt records.
- Emit telemetry about safeguards (backpressure/monitoring).
- Return a complete `process_batch(events, state)` implementation only.
"""

async def main(concurrent: bool = True, num_runs: int = 10):
    tools = [
        {
            "name": "python_expression",
            "description": "Execute Python (math, stats available).",
            "input_schema": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
        {
            "name": "submit_code",
            "description": "Submit improved process_batch implementation.",
            "input_schema": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    ]
    handlers = {"python_expression": python_tool, "submit_code": submit_tool}
    prompt = build_prompt()
    print("=" * 78)
    print("🛡️  RESILIENCE GAUNTLET — CASCADING BUG HUNT")
    print("=" * 78)
    print(f"Running {num_runs} evaluations...\n")
    tasks = [run_evaluation(i + 1, prompt, tools, handlers) for i in range(num_runs)]
    if concurrent:
        results = [await t for t in asyncio.as_completed(tasks)]
    else:
        results = [await t for t in tasks]
    passes = sum(passed for _, passed, _ in results)
    avg = sum(score for _, _, score in results) / num_runs
    rate = (passes / num_runs) * 100
    print("\n" + "=" * 78)
    print("📊 RESULTS")
    print("=" * 78)
    print(f"Passed: {passes}/{num_runs} ({rate:.1f}%)")
    print(f"Avg Score: {avg:.1%}")
    print("✅ Target met" if 10 <= rate <= 40 else "⚠️ Target 10-40% not met yet")

if __name__ == "__main__":
    asyncio.run(main(concurrent=True, num_runs=10))