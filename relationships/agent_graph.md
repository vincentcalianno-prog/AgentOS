# Agent Relationship Graph

This file maps how agents relate to, delegate to, and learn from each other.

## Graph Format
```
[AgentA] --delegates--> [AgentB]
[AgentA] --shares_skill--> [AgentC]
[AgentB] --learns_from--> [AgentA]
```

## Current Graph
*(No agents yet — graph will grow as agents are added)*

---

## Delegation Rules
- An agent may delegate a task only to agents listed as its `delegates_to` targets
- Delegation must pass the full context object, not just a summary
- The receiving agent must confirm capability before accepting

## Learning Rules
- When Agent A improves Skill X, all agents using Skill X are notified
- Notification format: update `shared_learnings.md` with `[SKILL UPDATE]` tag
