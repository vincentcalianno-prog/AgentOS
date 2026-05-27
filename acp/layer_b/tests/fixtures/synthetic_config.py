"""Synthetic WorkflowOrchestratorConfig for Agent 8 unit and integration tests.

Provides SYNTHETIC_CONFIG — a fully-populated WorkflowOrchestratorConfig that
uses only placeholder values (no deployment-specific endpoints or tokens).

Per Implementation Guide Section 7.1: synthetic fixtures only; no real
credentials, no Antora-specific identifiers.

NotificationRoute event_patterns used here:
    "sla_breach_detected"   — SLA violation alert
    "negotiation_paused"    — degraded mode / manual pause
    "negotiation_failed"    — pipeline failure
"""

from __future__ import annotations

from acp.layer_b.agents.workflow_orchestrator_config import (
    CredentialsConfig,
    ExtensionsConfig,
    NotificationRoute,
    OperationalConfig,
    OrganizationConfig,
    PlaybookConfig,
    WorkflowOrchestratorConfig,
)
from acp.layer_b.core.types import NegotiationState

# ---------------------------------------------------------------
# Notification routes — two synthetic recipients; channel hints
# ---------------------------------------------------------------
_ROUTES = (
    NotificationRoute(
        event_pattern="sla_breach_detected",
        recipient_id="alice",
        channel_preference="slack",
    ),
    NotificationRoute(
        event_pattern="sla_breach_detected",
        recipient_id="vincent",
        channel_preference="email",
        workflow_id="contract_redline",   # only for contract_redline workflow
    ),
    NotificationRoute(
        event_pattern="negotiation_paused",
        recipient_id="alice",
        channel_preference="slack",
    ),
    NotificationRoute(
        event_pattern="negotiation_failed",
        recipient_id="alice",
        channel_preference="slack",
    ),
    NotificationRoute(
        event_pattern="retry_exhausted",
        recipient_id="alice",
        channel_preference="slack",
    ),
)

# ---------------------------------------------------------------
# SLA thresholds: (workflow_id, status_value) → threshold days
# ---------------------------------------------------------------
_SLA_THRESHOLDS = {
    ("contract_redline", NegotiationState.NEGOTIATING.value): 10,
    ("contract_redline", NegotiationState.PENDING_SIGNATURE.value): 5,
}

# ---------------------------------------------------------------
# Full synthetic config
# ---------------------------------------------------------------
SYNTHETIC_CONFIG = WorkflowOrchestratorConfig(
    credentials=CredentialsConfig(
        slack_webhook_url="",
        smtp_host="",
        smtp_port=0,
        smtp_from_address="",
    ),
    operational=OperationalConfig(
        sla_thresholds=_SLA_THRESHOLDS,
        max_retry_attempts=3,
        retry_backoff_base_seconds=60,
        polling_interval_seconds=900,
    ),
    playbook=PlaybookConfig(
        legal_review_required_statuses=(),
        escalation_chain=("alice", "vincent"),
    ),
    organization=OrganizationConfig(
        notification_routes=_ROUTES,
        lookup_failure_policy="notify_for_triage",
    ),
    extensions=ExtensionsConfig(),
)
