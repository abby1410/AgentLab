import os
import sys
import json
import time
import difflib
import subprocess
from pathlib import Path
from datetime import datetime

import streamlit as st

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
RUNS = ROOT / "runs"
TESTS = ROOT / "tests"
SOLUTION = WORKSPACE / "solution.py"
CONFIG = ROOT / "task_config.json"
BACKUPS = RUNS / "ui-backups"

for directory in (WORKSPACE, RUNS, TESTS, BACKUPS):
    directory.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="AgentLab | Local AI Workbench",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------
# STYLING
# ---------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');

.stApp {
    background: #0b0d12;
    color: #edf0f6;
    font-family: 'Manrope', sans-serif;
}
[data-testid="stSidebar"] {
    background: #10131b;
    border-right: 1px solid #252a36;
}
[data-testid="stMetric"] {
    background: #131722;
    border: 1px solid #272d3b;
    padding: 18px;
    border-radius: 14px;
}
[data-testid="stMetricValue"] {
    color: #9cf6c8;
}
div[data-testid="stButton"] > button {
    border-radius: 9px;
    min-height: 42px;
    border: 1px solid #303747;
    font-weight: 700;
}
div[data-testid="stButton"] > button[kind="primary"] {
    background: #a4f5c9;
    color: #09110d;
    border: none;
}
.panel {
    background: #131722;
    border: 1px solid #272d3b;
    border-radius: 15px;
    padding: 20px;
    margin-bottom: 14px;
}
.muted {
    color: #929bad;
    font-size: 0.9rem;
}
.eyebrow {
    color: #9cf6c8;
    font-size: 0.76rem;
    font-weight: 800;
    letter-spacing: 0.13em;
}
h1, h2, h3 {
    letter-spacing: -0.035em;
}
code, pre {
    font-family: 'DM Mono', monospace !important;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
def load_config():
    default = {
        "task": (
            "Implement analyze_csv(csv_content: str) -> dict. "
            "The CSV has required columns id, name, email. "
            "Return total_rows, missing_required_fields, duplicate_ids, "
            "invalid_emails, and error. Follow tests/test_solution.py."
        ),
        "notes": "Preserve the existing test contract.",
    }
    if CONFIG.exists():
        try:
            saved = json.loads(CONFIG.read_text())
            return {**default, **saved}
        except (json.JSONDecodeError, OSError):
            pass
    return default


def save_config(task, notes):
    CONFIG.write_text(json.dumps({
        "task": task,
        "notes": notes,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))


def read_text(path):
    try:
        return path.read_text(errors="replace") if path.exists() else ""
    except OSError as exc:
        return f"Unable to read file: {exc}"


def list_reports():
    reports = []
    for path in RUNS.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            reports.append({
                "file": path.name,
                "path": path,
                "data": data,
                "modified": datetime.fromtimestamp(
                    path.stat().st_mtime
                ),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(reports, key=lambda x: x["modified"], reverse=True)


def run_command(command, cwd=ROOT, env=None):
    """Run a command and stream output into the dashboard."""
    output = st.empty()
    log_lines = []
    process_env = os.environ.copy()
    if env:
        process_env.update(env)

    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=process_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        with output.container():
            log_box = st.empty()
            for line in iter(process.stdout.readline, ""):
                log_lines.append(line.rstrip())
                log_box.code("\n".join(log_lines[-100:]), language="text")

            process.stdout.close()
            return_code = process.wait()

        return return_code, "\n".join(log_lines)

    except FileNotFoundError as exc:
        return 127, str(exc)
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def make_diff(before, after):
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="Before",
        tofile="After",
    ))


def infer_stage(line):
    text = line.lower()
    for keyword, stage in [
        ("manager", "Manager"),
        ("planning", "Manager"),
        ("developer", "Developer"),
        ("writing solution", "Developer"),
        ("qa", "QA"),
        ("test", "QA"),
        ("reviewer", "Reviewer"),
        ("review", "Reviewer"),
        ("repair", "Repair"),
        ("revision", "Repair"),
    ]:
        if keyword in text:
            return stage
    return "Workflow"


# ---------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚡ AgentLab")
    st.caption("LOCAL AI DEVELOPMENT WORKBENCH")
    st.divider()

    page = st.radio(
        "WORKSPACE",
        [
            "Overview",
            "Run Agents",
            "Quality & Tests",
            "Code Review",
            "Run History",
            "Project Files",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("**Runtime**")

    model = os.getenv("MODEL", "qwen2.5-coder:3b")
    st.code(model)

    ollama_status = st.empty()
    if st.button("Check Ollama", use_container_width=True):
        try:
            import ollama
            endpoint = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            client = ollama.Client(host=endpoint, timeout=10)
            result = client.list()
            ollama_status.success(f"Ollama is responding at {endpoint}")
            models = result.get("models", []) if isinstance(result, dict) else result.models
            ollama_status.code("\\n".join(
                getattr(model, "model", None) or model.get("name", "Unknown model")
                for model in models
            ) or "No models are currently available.")
        except Exception as exc:
            ollama_status.error(f"Could not reach Ollama: {type(exc).__name__}: {exc}")

    st.caption("Python · LangGraph · Ollama")


# ---------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------
if page == "Overview":
    st.markdown('<div class="eyebrow">YOUR LOCAL AGENT SYSTEM</div>',
                unsafe_allow_html=True)
    st.title("Build. Test. Improve.")
    st.markdown(
        "A local multi-agent workflow that turns a task into code, "
        "runs tests, reviews the evidence, and attempts repairs."
    )

    reports = list_reports()
    solution_text = read_text(SOLUTION)
    test_files = list(TESTS.glob("test_*.py"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Recorded runs", len(reports))
    c2.metric("Test files", len(test_files))
    c3.metric("Solution lines", len(solution_text.splitlines()))
    c4.metric("Workspace", "Local")

    st.markdown("### Workflow")
    stages = [
        ("01", "Manager", "Break down the task"),
        ("02", "Developer", "Write the implementation"),
        ("03", "QA", "Run automated tests"),
        ("04", "Reviewer", "Inspect results and evidence"),
        ("05", "Repair", "Attempt a bounded correction"),
    ]
    cols = st.columns(len(stages))
    for col, (number, title, desc) in zip(cols, stages):
        with col:
            st.markdown(
                f'<div class="panel"><span class="eyebrow">{number}</span>'
                f'<h3>{title}</h3><p class="muted">{desc}</p></div>',
                unsafe_allow_html=True,
            )

    st.markdown("### Recent runs")
    if reports:
        for report in reports[:5]:
            data = report["data"]
            with st.container(border=True):
                left, middle, right = st.columns([3, 2, 2])
                left.markdown(f"**{report['file']}**")
                middle.caption(report["modified"].strftime("%d %b %H:%M"))
                right.write(str(data.get("status", data.get("result", "Recorded"))))
    else:
        st.info("No JSON run reports found yet. Run your agents to start building history.")

    if st.button("＋ Start a run", type="primary"):
        st.session_state["page_jump"] = "Run Agents"
        st.rerun()


# ---------------------------------------------------------
# RUN AGENTS
# ---------------------------------------------------------
elif page == "Run Agents":
    st.markdown('<div class="eyebrow">EXECUTION CONTROL</div>',
                unsafe_allow_html=True)
    st.title("Run agents")
    st.caption("Configure the objective, inspect the current implementation, then launch the workflow.")

    config = load_config()

    with st.form("task_form"):
        task = st.text_area(
            "Task objective",
            value=config["task"],
            height=150,
            help="Saved to task_config.json. The current agent workflow must explicitly read this file for the objective to affect its prompts.",
        )
        notes = st.text_area(
            "Additional constraints",
            value=config.get("notes", ""),
            height=80,
        )
        save_clicked = st.form_submit_button("Save task configuration")

    if save_clicked:
        save_config(task, notes)
        st.success("Saved to task_config.json.")

    st.warning(
        "Important: saving a task does not automatically change the prompts "
        "inside agentlab.py. The workflow must be connected to this configuration "
        "before custom tasks can safely replace its existing objective."
    )

    st.markdown("### Pre-run checks")
    checks = [
        ("agentlab.py", (ROOT / "agentlab.py").exists()),
        ("solution.py", SOLUTION.exists()),
        ("tests directory", TESTS.exists()),
    ]
    cols = st.columns(len(checks))
    for col, (label, exists) in zip(cols, checks):
        col.write(("✅ " if exists else "❌ ") + label)

    st.markdown("### Current solution")
    st.code(read_text(SOLUTION)[:12000] or "# No solution.py found", language="python")

    st.markdown("### Launch")
    st.caption("A backup is created before execution. The workflow may modify workspace/solution.py.")

    confirm = st.checkbox("I understand that the agent workflow can modify solution.py")

    if st.button("▶ Run AgentLab", type="primary", disabled=not confirm):
        if not (ROOT / "agentlab.py").exists():
            st.error("agentlab.py was not found in the project root.")
        else:
            before = read_text(SOLUTION)

            if before:
                backup = BACKUPS / f"solution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
                backup.write_text(before)
                st.info(f"Pre-run backup: {backup.relative_to(ROOT)}")

            st.markdown("### Live execution log")
            st.caption("Output is streamed while the process runs.")

            started = time.time()
            return_code, output = run_command(
                [sys.executable, "-u", "agentlab.py"],
                env={
                    "AGENTLAB_TASK": task,
                    "AGENTLAB_NOTES": notes,
                },
            )
            elapsed = time.time() - started
            after = read_text(SOLUTION)

            st.session_state["last_run"] = {
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "return_code": return_code,
                "elapsed_seconds": round(elapsed, 2),
                "output": output,
                "before": before,
                "after": after,
                "diff": make_diff(before, after),
            }

            if return_code == 0:
                st.success(f"Workflow finished in {elapsed:.1f}s.")
            else:
                st.error(f"Workflow exited with code {return_code}. Check the execution log.")

            if before != after:
                st.markdown("### Change summary")
                st.write(f"Solution changed: {len(make_diff(before, after).splitlines())} diff lines.")
                with st.expander("Inspect code diff", expanded=True):
                    st.code(make_diff(before, after) or "No textual diff", language="diff")
            else:
                st.info("The solution file did not change during this run.")


# ---------------------------------------------------------
# QUALITY AND TESTS
# ---------------------------------------------------------
elif page == "Quality & Tests":
    st.markdown('<div class="eyebrow">DETERMINISTIC VALIDATION</div>',
                unsafe_allow_html=True)
    st.title("Quality & tests")
    st.caption("Run the test suite independently of the agent workflow.")

    test_files = list(TESTS.glob("test_*.py"))
    c1, c2 = st.columns(2)
    c1.metric("Test files discovered", len(test_files))
    c2.metric("Test framework", "pytest")

    if test_files:
        for file in test_files:
            st.write(f"• `{file.relative_to(ROOT)}`")
    else:
        st.warning("No test_*.py files found in tests/.")

    if st.button("▶ Run pytest", type="primary"):
        code, output = run_command([
            sys.executable, "-m", "pytest", "-v", "--tb=short"
        ])
        if code == 0:
            st.success("All tests passed.")
        else:
            st.error(f"pytest exited with code {code}.")
        st.code(output[-18000:] or "No output", language="text")

    st.markdown("### Latest workflow result")
    last = st.session_state.get("last_run")
    if last:
        a, b = st.columns(2)
        a.metric("Process exit code", last["return_code"])
        b.metric("Elapsed time", f'{last["elapsed_seconds"]}s')
    else:
        st.info("No workflow run in this dashboard session yet.")


# ---------------------------------------------------------
# CODE REVIEW
# ---------------------------------------------------------
elif page == "Code Review":
    st.markdown('<div class="eyebrow">INSPECT BEFORE ACCEPTING</div>',
                unsafe_allow_html=True)
    st.title("Code review")
    st.caption("Compare the current solution with the previous run snapshot.")

    last = st.session_state.get("last_run")

    if last:
        st.markdown("### Latest run diff")
        diff = last.get("diff", "")
        if diff:
            st.code(diff, language="diff")
        else:
            st.success("No differences detected.")
        with st.expander("Previous solution"):
            st.code(last.get("before", ""), language="python")
        with st.expander("Solution after run"):
            st.code(last.get("after", ""), language="python")
    else:
        st.info("Run AgentLab from the Run Agents page to generate an in-session diff.")

    st.markdown("### Current workspace solution")
    st.code(read_text(SOLUTION) or "# No solution.py found", language="python")

    st.markdown("### Restore a saved backup")
    backups = sorted(BACKUPS.glob("solution_*.py"), reverse=True)
    if backups:
        selected = st.selectbox(
            "Select backup",
            backups,
            format_func=lambda p: p.name,
        )
        if st.button("Restore selected backup"):
            st.session_state["restore_candidate"] = str(selected)
            st.warning("Review the selected file before confirming the restore.")

        candidate = st.session_state.get("restore_candidate")
        if candidate and Path(candidate).exists():
            st.code(read_text(Path(candidate)), language="python")
            if st.button("Confirm restore", type="primary"):
                current = read_text(SOLUTION)
                emergency = BACKUPS / f"before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
                emergency.write_text(current)
                SOLUTION.write_text(read_text(Path(candidate)))
                st.session_state.pop("restore_candidate", None)
                st.success("Backup restored. The previous version was also backed up.")
                st.rerun()
    else:
        st.caption("No UI-created solution backups found yet.")


# ---------------------------------------------------------
# RUN HISTORY
# ---------------------------------------------------------
elif page == "Run History":
    st.markdown('<div class="eyebrow">EXECUTION RECORDS</div>',
                unsafe_allow_html=True)
    st.title("Run history")

    reports = list_reports()
    if not reports:
        st.info("No readable JSON reports found in runs/.")
    else:
        st.write(f"{len(reports)} report(s) found.")
        for report in reports:
            data = report["data"]
            with st.expander(
                f"{report['file']}  ·  {report['modified'].strftime('%d %b %Y, %H:%M')}"
            ):
                st.json(data)
                st.caption(f"Location: {report['path'].relative_to(ROOT)}")

    st.markdown("### UI-created backups")
    backup_files = sorted(BACKUPS.glob("*.py"), reverse=True)
    if backup_files:
        for path in backup_files[:20]:
            st.write(f"`{path.relative_to(ROOT)}` · {path.stat().st_size:,} bytes")
    else:
        st.caption("No backups yet.")


# ---------------------------------------------------------
# PROJECT FILES
# ---------------------------------------------------------
elif page == "Project Files":
    st.markdown('<div class="eyebrow">LOCAL REPOSITORY</div>',
                unsafe_allow_html=True)
    st.title("Project files")

    candidate_files = [
        ROOT / "agentlab.py",
        ROOT / "app.py",
        CONFIG,
        WORKSPACE / "solution.py",
        TESTS / "test_solution.py",
    ]
    candidate_files += sorted(RUNS.glob("*.json"))

    existing = [p for p in candidate_files if p.exists()]
    if not existing:
        st.info("No project files found.")
    else:
        selected = st.selectbox(
            "Select a file",
            existing,
            format_func=lambda p: str(p.relative_to(ROOT)),
        )
        st.caption(f"{selected.stat().st_size:,} bytes")
        content = read_text(selected)
        language = "python" if selected.suffix == ".py" else "json" if selected.suffix == ".json" else "text"
        st.code(content[:30000], language=language)
        if len(content) > 30000:
            st.caption("Preview truncated to 30,000 characters.")

    st.markdown("### Project structure")
    for path in sorted(ROOT.iterdir()):
        if path.name.startswith(".") or path.name == "__pycache__":
            continue
        icon = "📁" if path.is_dir() else "📄"
        st.write(f"{icon} `{path.name}`")

