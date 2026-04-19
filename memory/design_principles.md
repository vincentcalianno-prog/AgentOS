# Design Principles

These principles govern how all agents and skills in this ecosystem are built.
Claude must apply these when creating anything new.

## 1. Unity of Thought
Every agent shares a common mental model. Before acting, an agent should ask:
"Does this decision align with what the other agents know and value?"

## 2. Single Responsibility
Each agent has one clear purpose. Skills are atomic and reusable.
Prefer composing small, tested skills over building monolithic agents.

## 3. Shared Memory First
Before solving a problem from scratch, check `memory/shared_learnings.md`.
After solving it, write back what you learned.

## 4. Explicit Interfaces
Every agent exposes a clear input/output contract.
Every skill declares its dependencies, inputs, and outputs in its header.

## 5. Progressive Trust
Agents start with limited autonomy. As they demonstrate reliability,
their permissions and inter-agent delegation rights expand.

## 6. Learn and Propagate
When one agent improves, that improvement should be evaluated for
propagation to all other agents via the registry.

## 7. Fail Gracefully
Every agent must handle failure without cascading. Log errors to
`memory/shared_learnings.md` with context so others can learn from it.
