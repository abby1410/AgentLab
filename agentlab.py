from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import TypedDict

import ollama
from langgraph.graph import END, START, StateGraph


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
TESTS = ROOT / "tests"
RUNS = ROOT / "runs"
BACKUPS = RUNS / "backups"

MODEL = os.getenv("AGENTLAB_MODEL", "qwen2.5-coder:3b")
MAX_REVISIONS = 2
TEST_TIMEOUT_SECONDS = 20

for directory in (WORKSPACE, TESTS, RUNS, BACKUPS):
    directory.mkdir(parents=True, exist_ok=True)


# ============================================================
# AUTHORITATIVE TASK CONTRACT
# Aligned with tests/test_solution.py
# ============================================================

TASK = """
Implement a CSV data quality analyzer in workspace/solution.py.

Public interface:
    analyze_csv(csv_content: str) -> dict

Required CSV headers: id, name, email.

The function must return a JSON-serializable dictionary with these keys:
- total_rows: number of data records, excluding the header.
- missing_required_fields: list of issues for empty or whitespace-only
  values in id, name, or email.
- duplicate_ids: list of duplicate-ID issues, including each duplicated
  ID and every CSV row number where it occurs.
- invalid_emails: list of issues for non-empty invalid email addresses.
- error: None on success, otherwise a descriptive error string.

CSV row numbers start at 2 for the first data row because row 1 is the header.
For duplicate IDs, report all row numbers for every duplicated ID.
Empty input returns zero rows, empty issue lists, and error=None.
Missing required headers must produce a descriptive error rather than crash.
Malformed CSV must produce a descriptive error rather than crash.
Use Python's standard library only.
Do not modify tests, access the network, or add dependencies.
Keep output deterministic and JSON serializable.
"""


# ============================================================
# WORKFLOW STATE
# ============================================================

class State(TypedDict, total=False):
    task: str
    plan: str
    code: str
    code_error: str
    test_output: str
    tests_passed: bool
    execution_error: bool
    review: str
    review_approved: bool
    approved: bool
    revisions: int
    events: list[dict]
    failure_signatures: list[str]
    started_at: float
    backup_created: bool
    backup_path: str
    candidate_written: bool


# ============================================================
# LOCAL MODEL
# ============================================================

def ask_agent(role: str, prompt: str) -> str:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are the {role} in a software engineering team. "
                    "Follow the supplied task contract exactly. "
                    "Use evidence, not assumptions. Never claim tests passed "
                    "unless the supplied test output proves it."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        options={
            "temperature": 0.1,
            "num_ctx": 4096,
        },
    )
    return response["message"]["content"].strip()


def record(state: State, agent: str, message: str) -> list[dict]:
    return state.get("events", []) + [
        {
            "time": time.time(),
            "agent": agent,
            "message": message[:5000],
        }
    ]


# ============================================================
# CODE VALIDATION
# ============================================================

def extract_python(text: str) -> str:
    text = text.strip()

    fenced = re.search(
        r"```(?:python)?[ \t]*\r?\n(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if fenced:
        text = fenced.group(1).strip()

    tree = ast.parse(text)

    has_analyzer = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "analyze_csv"
        for node in tree.body
    )

    if not has_analyzer:
        raise ValueError(
            "Generated code must define a top-level analyze_csv() function."
        )

    return text


def backup_solution() -> str:
    source = WORKSPACE / "solution.py"

    if not source.exists():
        return ""

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    destination = (
        BACKUPS
        / f"solution-{timestamp}-{uuid.uuid4().hex[:6]}.py"
    )

    shutil.copy2(source, destination)
    return str(destination)


def rollback_candidate(state: State) -> str:
    """Restore the pre-candidate solution after a failed QA run."""
    if not state.get("candidate_written", False):
        return ""

    backup_path = state.get("backup_path", "")
    target = WORKSPACE / "solution.py"

    if backup_path and os.path.isfile(backup_path):
        shutil.copy2(backup_path, target)
        return f"Restored previous solution from {backup_path}."

    return (
        "WARNING: Candidate failed, but no usable backup was found; "
        "automatic rollback was not possible."
    )


# ============================================================
# AGENT 1: MANAGER
# ============================================================

def manager(state: State) -> dict:
    prompt = f"""
AUTHORITATIVE TASK CONTRACT:
{state["task"]}

Write a short implementation plan and acceptance checklist.

Important:
- Required headers are id, name, email.
- The duplicate output key is duplicate_ids.
- total_rows excludes the CSV header.
- Do not invent alternative column names or output keys.
- Do not write implementation code.
- Keep the response under 180 words.
"""

    try:
        plan = ask_agent("Project Manager", prompt)
    except Exception as exc:
        plan = (
            "Use csv.DictReader. Validate the headers. Count only data rows. "
            "Detect blank values, duplicate IDs, invalid emails, empty input, "
            "missing columns, and malformed CSV. "
            f"Model error: {type(exc).__name__}: {exc}"
        )

    return {
        "plan": plan,
        "events": record(state, "manager", plan),
    }


# ============================================================
# AGENT 2: DEVELOPER
# ============================================================

def developer(state: State) -> dict:
    previous_code = state.get("code", "")
    previous_tests = state.get("test_output", "No previous test run.")
    previous_error = state.get("code_error", "")
    review = state.get("review", "No reviewer feedback yet.")
    signatures = state.get("failure_signatures", [])

    repeated_failure = ""

    if len(signatures) >= 2 and signatures[-1] == signatures[-2]:
        repeated_failure = """
CRITICAL: The last two attempts produced the same failure signature.
Do not reproduce the previous implementation. Change the underlying logic.
"""

    prompt = f"""
You are the Python Developer working on attempt {len(signatures) + 1}.

AUTHORITATIVE TASK CONTRACT:
{state["task"]}

MANAGER PLAN:
{state.get("plan", "")}

PREVIOUS IMPLEMENTATION:
{previous_code[:7000] or "[No previous implementation]"}

PREVIOUS CODE VALIDATION ERROR:
{previous_error or "None"}

LATEST ACTUAL PYTEST OUTPUT:
{previous_tests[-9000:]}

REVIEWER FEEDBACK:
{review[:4000]}

{repeated_failure}

REPAIR INSTRUCTIONS:

If tests failed:
1. Identify each failing test from the actual output.
2. Trace it to the specific defective code.
3. Correct the root cause, not just one example.
4. Preserve behavior that already passed.
5. Do not return the same broken implementation unchanged.

The exact expected interface is:
    analyze_csv(csv_content: str) -> dict

The required CSV columns are id, name, email.
The required output keys are:
    total_rows
    missing_required_fields
    duplicate_ids
    invalid_emails
    error

Common defects to check:
- Counting the header as a data row.
- Using customer_id instead of id.
- Returning duplicate_customer_ids instead of duplicate_ids.
- Detecting duplicate IDs without retaining every row number.
- Checking whether an email is non-empty but not validating its format.
- Failing to handle missing columns or malformed CSV.
- Returning a different dictionary schema on error.
- Treating whitespace-only values as valid.

Use only the Python standard library.
Do not modify tests or access the network.

Return the complete contents of solution.py.
Return Python code only, without Markdown fences or explanations.
"""

    try:
        answer = ask_agent("Python Developer", prompt)
        code = extract_python(answer)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

        return {
            "code_error": error,
            "backup_path": "",
            "candidate_written": False,
            "events": record(
                state,
                "developer",
                f"Code generation or validation failed: {error}",
            ),
        }

    target = WORKSPACE / "solution.py"
    backup_path = ""

    if target.exists():
        try:
            backup_path = backup_solution()
        except Exception as exc:
            error = f"Could not back up existing solution: {exc}"
            return {
                "code_error": error,
                "backup_path": "",
                "candidate_written": False,
                "events": record(state, "developer", error),
            }

    try:
        target.write_text(code + "\n", encoding="utf-8")
    except Exception as exc:
        error = f"Could not write candidate solution: {exc}"
        return {
            "code_error": error,
            "backup_path": backup_path,
            "candidate_written": False,
            "events": record(state, "developer", error),
        }

    message = (
        f"Generated syntax-valid candidate solution.py "
        f"({len(code)} characters)."
    )

    if backup_path:
        message += f" Previous solution backed up to {backup_path}."

    return {
        "code": code,
        "code_error": "",
        "backup_created": True,
        "backup_path": backup_path,
        "candidate_written": True,
        "events": record(state, "developer", message),
    }


# ============================================================
# AGENT 3: QA
# Pytest is the source of truth.
# ============================================================

def qa(state: State) -> dict:
    code_error = state.get("code_error", "")

    if code_error:
        output = (
            "GENERATION VALIDATION FAILURE\n"
            f"{code_error}\n"
            "Generate valid Python defining analyze_csv()."
        )

        return {
            "test_output": output,
            "tests_passed": False,
            "execution_error": True,
            "candidate_written": False,
            "failure_signatures": (
                state.get("failure_signatures", [])
                + ["GENERATION_ERROR"]
            ),
            "events": record(state, "qa", output),
        }

    target = WORKSPACE / "solution.py"
    test_file = TESTS / "test_solution.py"

    if not target.exists() or not test_file.exists():
        missing = target if not target.exists() else test_file
        output = f"Required file not found: {missing}"
        rollback_message = rollback_candidate(state)
        if rollback_message:
            output += "\n" + rollback_message

        return {
            "test_output": output,
            "tests_passed": False,
            "execution_error": True,
            "candidate_written": False,
            "failure_signatures": (
                state.get("failure_signatures", [])
                + ["MISSING_FILE"]
            ),
            "events": record(state, "qa", output),
        }

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(WORKSPACE)
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                str(test_file),
            ],
            cwd=WORKSPACE,
            env=env,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
            shell=False,
        )

        output = (
            f"Exit code: {result.returncode}\n"
            f"STDOUT:\n{result.stdout[-8000:]}\n"
            f"STDERR:\n{result.stderr[-4000:]}"
        )

        passed = result.returncode == 0
        combined = result.stdout + result.stderr

        execution_error = (
            result.returncode != 0
            and any(
                marker in combined
                for marker in (
                    "ERROR collecting",
                    "SyntaxError",
                    "ModuleNotFoundError",
                    "ImportError",
                )
            )
        )

        failing_names = sorted(
            set(re.findall(r"FAILED\s+([^\s]+)", result.stdout))
        )

        signature = (
            "PASS"
            if passed
            else "|".join(failing_names) or "TEST_FAILURE"
        )

    except subprocess.TimeoutExpired:
        output = (
            f"TEST TIMEOUT: exceeded {TEST_TIMEOUT_SECONDS} seconds."
        )
        passed = False
        execution_error = True
        signature = "TEST_TIMEOUT"

    except Exception as exc:
        output = (
            f"TEST EXECUTION ERROR: {type(exc).__name__}: {exc}"
        )
        passed = False
        execution_error = True
        signature = "TEST_EXECUTION_ERROR"

    if not passed:
        rollback_message = rollback_candidate(state)
        if rollback_message:
            output += "\n" + rollback_message

    return {
        "test_output": output,
        "tests_passed": passed,
        "execution_error": execution_error,
        "candidate_written": False,
        "failure_signatures": (
            state.get("failure_signatures", []) + [signature]
        ),
        "events": record(state, "qa", output),
    }


# ============================================================
# AGENT 4: REVIEWER
# ============================================================

def reviewer(state: State) -> dict:
    prompt = f"""
Review the implementation using the task contract and actual test evidence.

TASK:
{state["task"]}

IMPLEMENTATION:
{state.get("code", "[No valid implementation]")[:7000]}

ACTUAL QA OUTPUT:
{state.get("test_output", "")[-9000:]}

Tests passed: {state.get("tests_passed", False)}
Execution error: {state.get("execution_error", False)}

Return JSON only:
{{
  "decision": "APPROVE" or "REVISE",
  "failure_type": "none, syntax, test_failure, execution_error, or requirement_gap",
  "evidence": "specific evidence",
  "next_action": "specific correction"
}}

If tests failed, decision MUST be REVISE.
Approve only if tests passed and the implementation satisfies the contract.
"""

    try:
        raw = ask_agent("Independent Code Reviewer", prompt)
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        parsed = json.loads(match.group(0)) if match else None
    except Exception as exc:
        parsed = {
            "decision": "REVISE",
            "failure_type": "review_error",
            "evidence": f"{type(exc).__name__}: {exc}",
            "next_action": "Use actual pytest output to repair the code.",
        }

    if not isinstance(parsed, dict):
        parsed = {
            "decision": "REVISE",
            "failure_type": "review_format_error",
            "evidence": "Reviewer did not return valid JSON.",
            "next_action": "Use actual pytest output to repair the code.",
        }

    tests_passed = bool(state.get("tests_passed", False))

    # Deterministic approval gate: an LLM cannot overrule failed tests.
    approved = (
        str(parsed.get("decision", "")).upper() == "APPROVE"
        and tests_passed
        and not state.get("execution_error", False)
        and not state.get("code_error", "")
    )

    review_text = json.dumps(parsed, ensure_ascii=False)

    if not tests_passed:
        review_text += (
            "\nDeterministic gate: tests failed; approval is blocked."
        )

    revisions = state.get("revisions", 0)

    if not approved:
        revisions += 1

    return {
        "review": review_text,
        "review_approved": approved,
        "approved": approved,
        "revisions": revisions,
        "events": record(state, "reviewer", review_text),
    }


# ============================================================
# ROUTING
# ============================================================

def route_after_review(state: State) -> str:
    if (
        state.get("tests_passed", False)
        and state.get("review_approved", False)
        and not state.get("execution_error", False)
        and not state.get("code_error", "")
    ):
        return "finish"

    if state.get("revisions", 0) <= MAX_REVISIONS:
        return "developer"

    return "finish"


# ============================================================
# REPORT
# ============================================================

def finish(state: State) -> dict:
    success = (
        bool(state.get("tests_passed", False))
        and bool(state.get("review_approved", False))
        and not bool(state.get("execution_error", False))
        and not bool(state.get("code_error", ""))
    )

    report = {
        "task": state.get("task", TASK),
        "model": MODEL,
        "success": success,
        "tests_passed": state.get("tests_passed", False),
        "review_approved": state.get("review_approved", False),
        "execution_error": state.get("execution_error", False),
        "code_error": state.get("code_error", ""),
        "revisions": state.get("revisions", 0),
        "final_review": state.get("review", ""),
        "test_output": state.get("test_output", ""),
        "elapsed_seconds": round(
            time.time() - state.get("started_at", time.time()), 2
        ),
        "events": state.get("events", []),
    }

    report_path = RUNS / (
        f"run-{time.strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid.uuid4().hex[:6]}.json"
    )

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print(f"AgentLab result: {'SUCCESS' if success else 'NOT APPROVED'}")
    print(f"Model: {MODEL}")
    print(f"Tests passed: {report['tests_passed']}")
    print(f"Reviewer approved: {report['review_approved']}")
    print(f"Revisions used: {report['revisions']}")
    print(f"Report: {report_path}")
    print("-" * 60)
    print(report["test_output"])

    if not success:
        print("\nFinal reviewer feedback:")
        print(report["final_review"])

    print("=" * 60)
    return {}


# ============================================================
# LANGGRAPH WORKFLOW
# ============================================================

def build_graph():
    graph = StateGraph(State)

    graph.add_node("manager", manager)
    graph.add_node("developer", developer)
    graph.add_node("qa", qa)
    graph.add_node("reviewer", reviewer)
    graph.add_node("finish", finish)

    graph.add_edge(START, "manager")
    graph.add_edge("manager", "developer")
    graph.add_edge("developer", "qa")
    graph.add_edge("qa", "reviewer")

    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            "developer": "developer",
            "finish": "finish",
        },
    )

    graph.add_edge("finish", END)
    return graph.compile()


if __name__ == "__main__":
    # The dashboard can supply additional task instructions through
    # environment variables. The original CSV contract remains authoritative.
    dashboard_task = os.getenv("AGENTLAB_TASK", "").strip()
    dashboard_notes = os.getenv("AGENTLAB_NOTES", "").strip()

    task_parts = [TASK]

    if dashboard_task and dashboard_task != TASK:
        task_parts.append(
            "\n\nADDITIONAL DASHBOARD REQUEST:\n" + dashboard_task
        )

    if dashboard_notes:
        task_parts.append(
            "\n\nADDITIONAL CONSTRAINTS:\n" + dashboard_notes
        )

    initial_state: State = {
        "task": "\n".join(task_parts),
        "revisions": 0,
        "events": [],
        "failure_signatures": [],
        "started_at": time.time(),
        "backup_created": False,
        "backup_path": "",
        "candidate_written": False,
    }

    print(f"Starting AgentLab with local model: {MODEL}", flush=True)
    print("Manager -> Developer -> QA -> Reviewer -> Repair loop", flush=True)
    print("Streaming workflow events as each node completes.", flush=True)

    graph = build_graph()

    try:
        for chunk in graph.stream(initial_state, stream_mode="updates"):
            for node_name, update in chunk.items():
                print(
                    f"\n[{time.strftime('%H:%M:%S')}] "
                    f"NODE: {node_name.upper()}",
                    flush=True,
                )

                if not isinstance(update, dict):
                    print(str(update)[:1500], flush=True)
                    continue

                events = update.get("events", [])
                if events:
                    event = events[-1]
                    agent = event.get("agent", node_name)
                    message = event.get("message", "")
                    print(f"AGENT: {agent}", flush=True)
                    print(message[:4000], flush=True)

                if node_name == "finish":
                    print("Workflow report generated.", flush=True)

    except KeyboardInterrupt:
        print("\nAgentLab interrupted by user.", flush=True)
        raise
    except Exception as exc:
        print(
            f"\nWORKFLOW ERROR: {type(exc).__name__}: {exc}",
            flush=True,
        )
        raise
