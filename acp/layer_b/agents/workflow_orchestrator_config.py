"""Config dataclasses for Agent 8 (Workflow Orchestrator).

WorkflowOrchestratorConfig is the single structured object passed to Agent 8's
constructor. It is divided into five sub-configs by deployment contract category.
All sub-configs are frozen dataclasses — safe to share across threads and to
pass deep into the call stack without fear of mutation.

Design intent:
  - Required fields have NO defaults; a misconfigured deployment fails loudly
    at import time rather than silently at runtime.
  - Optional fields have SAFE defaults so simple test configs only need to
    specify what they care about.
  - No Antora-specific values live here. Antora's actual config lives in
    layer_c_antora/. Other deployments supply their own.
  - Phase 1 stubs (CredentialsConfig, PlaybookConfig, ExtensionsConfig) are
    documented as "Phase 1: stub" so future work is clearly located.

Category map:
    Cat 1  CredentialsConfig   — external endpoints / tokens (Phase 1: stubs)
    Cat 2  OperationalConfig   — SLA thresholds, retry budgets, polling params
    Cat 3  PlaybookConfig      — escalation rules, legal triggers (Phase 1: stubs)
    Cat 4  OrganizationConfig  — notification routes, lookup-failure policy
    Cat 5  ExtensionsConfig    — custom workflow hooks (Phase 1: stubs)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Cat 1 — Credentials
# ============================================================

@dataclass(frozen=True)
class CredentialsConfig:
    """External service credentials.

    Phase 1: all fields are placeholders — notification delivery is Layer C.
    Agent 8 declares intent via NOTIFICATION_REQUIRED events; the deployment's
    notification service (Layer C) holds real tokens and delivers messages.
    """
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 0
    smtp_from_address: str = ""


# ============================================================
# Cat 2 — Operational
# ============================================================

@dataclass(frozen=True)
class OperationalConfig:
    """SLA thresholds, retry budgets, and polling parameters.

    sla_thresholds maps (workflow_id, status) pairs to a stall threshold in
    days. Agent 8's scan_sla_violations() iterates this dict and calls Agent 9
    for each entry. Example:
        {
            ("contract_redline", "Negotiating"): 10,
            ("contract_redline", "Pending Signature"): 5,
        }

    max_retry_attempts: after this many attempts, Agent 8 enters degraded mode
    for the negotiation and stops retrying.

    retry_backoff_base_seconds: base for exponential back-off between retries.
    Layer C's retry scheduler uses this; Agent 8 records state only.

    polling_interval_seconds: how often Layer C should invoke scan_sla_violations()
    and retry_failed_event(). Agent 8 has no internal scheduler.
    """
    sla_thresholds: dict                # {(workflow_id, status): int (days)} — required
    max_retry_attempts: int             # required, no default
    retry_backoff_base_seconds: int = 60
    polling_interval_seconds: int = 900  # 15 minutes


# ============================================================
# Cat 3 — Playbook
# ============================================================

@dataclass(frozen=True)
class PlaybookConfig:
    """Escalation rules and legal-review triggers.

    Phase 1: stub. Escalation policy is richer in future phases when the
    Steering Group governance layer (Section 5.9 of the spec) is built out.

    legal_review_required_statuses: tuple of NegotiationState.value strings
    that automatically require legal review (regardless of LRS content).

    escalation_chain: ordered tuple of recipient_ids for multi-tier escalation.
    First contact is notified on first breach; second on second breach; etc.
    Matches the spec's "first Slack, second Gmail, third Ranjeet" pattern.
    """
    legal_review_required_statuses: tuple = ()
    escalation_chain: tuple = ()           # tuple[str, ...] of recipient_ids


# ============================================================
# Cat 4 — Organization
# ============================================================

@dataclass(frozen=True)
class NotificationRoute:
    """A single routing rule: event pattern → recipient + channel.

    Agent 8's route_notification() iterates the OrganizationConfig.notification_routes
    list and emits one NOTIFICATION_REQUIRED per matching route.

    Matching rules:
      - event_pattern must exactly match the source event's event_type.
      - If workflow_id is set, it must also match the source event's workflow_id.
      - If workflow_id is None, the route matches all workflows.

    channel_preference is a hint to the Layer C notification service.
    Supported values: "slack", "email", "sms". Layer C may ignore or
    override this based on deployment policy.
    """
    event_pattern: str       # exact event_type string to match
    recipient_id: str        # opaque identifier; Layer C maps to Slack handle / email
    channel_preference: str  # "slack" | "email" | "sms"
    workflow_id: Optional[str] = None  # None = match all workflows


@dataclass(frozen=True)
class OrganizationConfig:
    """Notification routing and lookup-failure policy.

    notification_routes: tuple of NotificationRoute objects, evaluated in
    order. All matching routes fire (not first-match-only).

    lookup_failure_policy controls Agent 8's resolve_inbox_event() behaviour
    when an inbox thread cannot be matched to a known negotiation:
      "notify_for_triage"       — emit NOTIFICATION_REQUIRED for human handling
                                  (default; safe for Phase 1)
      "auto_create_negotiation" — raise NotImplementedError (Phase 1 stub;
                                  full implementation deferred)
      "drop_silently"           — audit a warning, return None, no notification
    """
    notification_routes: tuple                     # tuple[NotificationRoute, ...]
    lookup_failure_policy: str = "notify_for_triage"


# ============================================================
# Cat 5 — Extensions
# ============================================================

@dataclass(frozen=True)
class ExtensionsConfig:
    """Custom workflow definitions and orchestration rules.

    Phase 1: stub. Future workflows (RFQ, Supplier Risk, etc.) register
    custom orchestration hooks here so Agent 8 can apply them without
    hard-coded workflow-specific logic.
    """
    custom_workflow_definitions: tuple = ()   # tuple of future WorkflowDefinition objects
    custom_orchestration_rules: tuple = ()    # tuple of future OrchestrationRule objects


# ============================================================
# Top-level config
# ============================================================

@dataclass(frozen=True)
class WorkflowOrchestratorConfig:
    """Complete configuration for Agent 8 (Workflow Orchestrator).

    All five sub-configs are required — a deployment that omits any category
    will fail at construction time with a TypeError, not silently at runtime.

    Usage (Layer C):
        config = WorkflowOrchestratorConfig(
            credentials=CredentialsConfig(slack_webhook_url="https://..."),
            operational=OperationalConfig(
                sla_thresholds={("contract_redline", "Negotiating"): 10},
                max_retry_attempts=3,
            ),
            playbook=PlaybookConfig(escalation_chain=("alice", "vincent")),
            organization=OrganizationConfig(
                notification_routes=(
                    NotificationRoute("retry_exhausted", "alice", "slack"),
                ),
            ),
            extensions=ExtensionsConfig(),
        )
    """
    credentials: CredentialsConfig
    operational: OperationalConfig
    playbook: PlaybookConfig
    organization: OrganizationConfig
    extensions: ExtensionsConfig
