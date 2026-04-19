# Agent: [AGENT_NAME]

## Identity
- **Agent ID:** `agent_[short_id]`
- **Version:** `0.1.0`
- **Created:** YYYY-MM-DD
- **Status:** `draft` | `active` | `deprecated`

## Purpose
*One sentence: what this agent does and why it exists.*

## Responsibilities
- Primary: ...
- Secondary: ...

## Skills Used
| Skill ID | Skill Name | Purpose in this Agent |
|----------|------------|----------------------|
| skill_xxx | ... | ... |

## Input Contract
```json
{
  "input_field": "type — description"
}
```

## Output Contract
```json
{
  "output_field": "type — description"
}
```

## Delegates To
- `agent_xxx` — when condition Y is met

## Learns From
- `agent_xxx` — subscribes to updates on skill_yyy

## Failure Handling
- On error: log to `memory/shared_learnings.md` with tag `[AGENT_ERROR]`
- Retry policy: ...
- Fallback: ...

## Changelog
| Version | Date | Change |
|---------|------|--------|
| 0.1.0 | YYYY-MM-DD | Initial draft |
