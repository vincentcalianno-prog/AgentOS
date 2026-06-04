# AgentOS

> A living registry and shared brain for an interconnected ecosystem of AI agents.

## What Is This?

AgentOS is a centralized repository that:
- Defines and tracks all agents and skills
- Stores shared memory and learnings across agents
- Maps how agents relate to and learn from each other
- Provides templates so new agents are built consistently

Claude reads this registry at the start of every agent-building session,
ensuring all agents are unified in thought and design.

## Development Setup (ACP)

The `acp/` directory contains the Agent Contract Platform sub-project with a full
Python test suite. Requirements: **Python 3.12+**.

```bash
git clone <repo-url>
cd AgentOS
make setup    # creates .venv, installs deps
make check    # runs 409 tests + discipline check — both must be green
```

Individual targets:

| Target | What it does |
|--------|-------------|
| `make setup` | Creates `.venv` with Python 3.12, installs `requirements-dev.txt` and the `acp` package in editable mode |
| `make test` | Runs the full Layer B test suite via pytest |
| `make discipline` | Runs `acp/discipline_check.py` (Layer A/B/C naming and boundary rules) |
| `make check` | Runs `test` + `discipline` — the pre-commit gate |
| `make clean` | Removes `.venv` and all `__pycache__` / `.pytest_cache` trees |

> **pyenv users:** A `.python-version` file pinning `3.12` is at the repo root.

## Structure

```
AgentOS/
├── REGISTRY.md              ← Master index (start here)
├── README.md                ← This file
├── agents/                  ← One file per agent
├── skills/                  ← One file per skill
├── memory/
│   ├── shared_learnings.md  ← Collective memory log
│   └── design_principles.md ← Core philosophy
├── relationships/
│   └── agent_graph.md       ← How agents connect
└── templates/
    ├── agent_template.md    ← Use this to create new agents
    └── skill_template.md    ← Use this to create new skills
```

## How Claude Uses This

At the start of any agent-building session, Claude will:
1. Read `REGISTRY.md` for the current state of the ecosystem
2. Check `memory/shared_learnings.md` for relevant patterns
3. Use `templates/` to scaffold new agents/skills consistently
4. Update the registry after building

## Primary Source of Truth

**Google Drive** → `AgentOS/` folder (Claude reads/writes via MCP)  
**GitHub** → This repo (mirrored backup + version history)

## Versioning

- Registry version lives in the footer of `REGISTRY.md`
- Each agent and skill tracks its own version in its file header
- GitHub commit history provides full audit trail
