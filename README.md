# AgentLab

**A local-first, multi-agent coding workbench.** AgentLab uses a Manager → Developer → QA → Reviewer → Repair workflow to generate a Python implementation, run deterministic tests, inspect the evidence, and attempt bounded repairs.

The Streamlit dashboard provides an overview, run controls, test execution, code review, run history, and project-file inspection.

## Screenshots

The interface walkthrough screenshots are included in the project screenshots bundle shared with this repository's maintainer.

## Architecture

- **UI:** Streamlit (`app.py`)
- **Orchestration:** LangGraph (`agentlab.py`)
- **Model runtime:** Ollama
- **Default model:** `qwen2.5-coder:3b`
- **Validation:** pytest

AgentLab is intentionally local-first. The agents operate on the project workspace and use the repository's test suite as the source of truth. Do not point it at a directory containing important code without reviewing its backup and file-write behavior first.

## Run locally

Requires Python 3.10+ and [Ollama](https://ollama.com/).

```bash
git clone https://github.com/abby1410/AgentLab.git
cd AgentLab

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate

python -m pip install --upgrade pip
pip install -r requirements.txt

ollama pull qwen2.5-coder:3b
ollama serve                    # if Ollama is not already running

streamlit run app.py
```

Open the local URL printed by Streamlit (usually http://localhost:8501).

## Deploy the dashboard with Streamlit Community Cloud

1. Push this repository to GitHub.
2. In [Streamlit Community Cloud](https://share.streamlit.io/), create an app from `abby1410/AgentLab`, branch `main`, entry point `app.py`.
3. Add the secrets below in the app's **Settings → Secrets**.
4. Deploy and verify the app's **Check Ollama** action before starting an agent run.

```toml
OLLAMA_HOST = "https://YOUR-REACHABLE-OLLAMA-ENDPOINT"
AGENTLAB_MODEL = "qwen2.5-coder:3b"
```

**Important runtime requirement:** Streamlit Community Cloud does not run the Ollama daemon from this repository, and it cannot reach Ollama running on your personal laptop at `localhost`. You must provide an Ollama server reachable from the deployed app, with the requested model already available. Protect that endpoint with authentication/network controls and TLS; do not expose an unauthenticated Ollama port to the public internet.

The Streamlit dashboard can be hosted independently, but agent execution, test subprocesses, workspace file writes, and run history happen on the Streamlit app's server filesystem. Cloud-hosted files may be ephemeral and should not be treated as durable storage. For a persistent, private, production setup, deploy the UI and Ollama runtime in infrastructure you control with persistent storage and restricted access.

## Configuration

| Variable / secret | Default | Purpose |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `AGENTLAB_MODEL` | `qwen2.5-coder:3b` | Model used by the agent workflow |

## Tests

```bash
python -m pytest -v --tb=short
```

The dashboard also exposes the test suite under **Quality & Tests**. The test suite validates the sample CSV analyzer workflow; it does not certify arbitrary code generated for other tasks.

## Safety notes

- Review generated diffs before using generated code.
- Run AgentLab in a disposable workspace or isolated environment.
- Do not store credentials or sensitive source code in the workspace.
- Do not expose the Streamlit app publicly if untrusted users can trigger code execution.
- Keep backups and test results outside ephemeral cloud storage if you need them long term.

## Current scope

AgentLab is an experimental developer workbench, not a secure multi-tenant code execution service. It does not provide user authentication, tenant isolation, a durable job queue, or hardened sandboxing by default.
