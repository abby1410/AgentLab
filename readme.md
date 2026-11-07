# AgentLab ⚡

**A local AI development workbench for writing, testing, reviewing, and iterating on Python code.**

AgentLab pairs a Streamlit dashboard with a LangGraph workflow and a local Ollama model. Its engineering loop is:

`Manager → Developer → QA → Reviewer → Repair`

## What it does

- Plans an implementation against a task contract.
- Generates or revises `workspace/solution.py`.
- Runs the project acceptance tests with pytest.
- Reviews the implementation against actual test output.
- Attempts a bounded repair loop when checks fail.
- Saves JSON run reports and backups locally.

The dashboard includes Overview, Run Agents, Quality & Tests, Code Review, Run History, and Project Files views.

## Stack

Python · Streamlit · LangGraph · Ollama · pytest

Default model: `qwen2.5-coder:3b` (override with `AGENTLAB_MODEL`).

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com/) installed and running
- The default model downloaded locally

## Setup

```bash
git clone https://github.com/abby1410/AgentLab.git
cd AgentLab

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

ollama pull qwen2.5-coder:3b
streamlit run app.py
```

If Ollama is not already running as a background service, start it in a separate terminal with `ollama serve`. On Windows, create the environment with `py -m venv .venv` and activate it with `.venv\\Scripts\\Activate.ps1`.

To run the agent workflow without the dashboard:

```bash
python agentlab.py
```

## Project layout

```text
AgentLab/
├── app.py                 # Streamlit dashboard
├── agentlab.py            # LangGraph workflow
├── requirements.txt
├── task_config.json
├── tests/
│   └── test_solution.py   # Acceptance tests
├── workspace/
│   └── solution.py        # Generated implementation
└── runs/                  # Local reports and backups
```

## Current scope and caveats

- The workflow is currently built around the CSV-analyzer contract in `agentlab.py` and `tests/test_solution.py`.
- Dashboard task text is appended as additional instructions; it does not replace the original CSV contract. This is not yet a fully generic coding agent.
- Failed pytest runs block reviewer approval. The bounded repair loop is an attempt, not a guarantee.
- Generated code is executed locally. Review changes and only run tasks and prompts you trust.
- Run reports, generated code, and backups are runtime artifacts; keep them local unless you deliberately want to version them.

## Roadmap

- [ ] Make task configuration the single source of truth for arbitrary tasks
- [ ] Support configurable test commands and acceptance criteria
- [ ] Add richer run comparison and evaluation metrics
- [ ] Add project templates beyond the current Python task

## License

No license file is currently included. All rights remain with the repository owner unless a license is added.
