# AgentOS — Central Agent Registry
> **This file is the single source of truth for all agents, skills, and shared knowledge.**
> Claude must read this file at the start of every agent-building session.

---

## 📋 How to Use This Registry

1. **Before building a new agent** → read `REGISTRY.md` + `agents/` to avoid duplication
2. **Before writing a skill** → check `skills/` to see if it already exists or can be extended
3. **After building** → update the relevant section below and add the agent/skill file
4. **Learnings & patterns** → write to `memory/shared_learnings.md`

---

## 🤖 Agent Index

| Agent ID | Name | Purpose | Status | File |
|----------|------|---------|--------|------|
| *(none yet)* | — | — | — | — |

---

## 🛠 Skill Index

| Skill ID | Name | Description | Used By | File |
|----------|------|-------------|---------|------|
| *(none yet)* | — | — | — | — |

---

## 🧠 Shared Memory

- [`memory/shared_learnings.md`](memory/shared_learnings.md) — Patterns, mistakes, and improvements discovered across agents
- [`memory/design_principles.md`](memory/design_principles.md) — Core philosophy guiding all agent and skill creation

---

## 🔗 Relationships

- [`relationships/agent_graph.md`](relationships/agent_graph.md) — How agents connect, delegate to, and learn from each other

---

## 📐 Templates

- [`templates/agent_template.md`](templates/agent_template.md) — Starter template for new agents
- [`templates/skill_template.md`](templates/skill_template.md) — Starter template for new skills

---

*Last updated: 2026-04-18 | Version: 0.1.0*
