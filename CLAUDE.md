# AgentOS Repository

This repo contains multiple agent projects. For the ACP (Agent Contract Platform) sub-project, the project primer is the orientation document:

  docs/ACP_Antora_Project_Primer_v1.docx

For Claude Code sessions working on ACP, open and read that primer first. It contains:
- What ACP is and why it exists
- Architecture summary with pointers to full specs
- What's been built so far
- Antora-specific context (people, integrations, tracker state)
- Working conventions (Layer A/B/C discipline, naming rules)
- What's next on the work plan

The full architecture specification is at docs/ACP_Architecture_Spec_v2_4.docx.
The implementation guide is at docs/ACP_Implementation_Guide_v1_1.docx.

The code lives in the acp/ directory. Run tests:
  python3 -m unittest acp.layer_b.tests.unit.test_state_manager

Run discipline check:
  python3 acp/discipline_check.py

Both must pass before any commit to a feature branch.
