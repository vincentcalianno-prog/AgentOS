"""Tenancy enforcement module.

Per Architecture Spec Section 4.1 and Implementation Guide Section 6:
every state-modifying operation goes through tenancy checks. Cross-tenant
writes are rejected at the API level, not by convention.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from acp.layer_b.core.adapters.audit_adapter import AuditLogAdapter, AuditEvent
from acp.layer_b.core.types import (
    TenantContext,
    TenancyViolation,
    ROLE_PORTFOLIO_AGGREGATOR,
)


class TenancyEnforcer:
    """Enforces tenant scope on every operation.

    Holds a reference to the audit log so every violation is recorded.
    """

    def __init__(self, audit: AuditLogAdapter):
        self._audit = audit

    def assert_can_write(self, context: TenantContext, target_tenant: str) -> None:
        """Raise TenancyViolation if context cannot write to target_tenant.

        Default rule: a tenant can only write to their own scope. No exceptions
        for cross-tenant writes (Agent 9 is read-only).
        """
        if context.tenant_id != target_tenant:
            self._record_violation(context, target_tenant, "write")
            raise TenancyViolation(
                f"Tenant '{context.tenant_id}' cannot write to tenant '{target_tenant}'"
            )

    def assert_can_read(self, context: TenantContext, target_tenant: str) -> None:
        """Raise TenancyViolation if context cannot read from target_tenant.

        Same-tenant reads are always allowed. Cross-tenant reads require
        the portfolio_aggregator role.
        """
        if context.tenant_id == target_tenant:
            return
        if context.has_role(ROLE_PORTFOLIO_AGGREGATOR):
            return
        self._record_violation(context, target_tenant, "read")
        raise TenancyViolation(
            f"Tenant '{context.tenant_id}' cannot read from tenant '{target_tenant}'"
        )

    def assert_can_read_cross_tenant(self, context: TenantContext) -> None:
        """Raise TenancyViolation unless context has portfolio_aggregator role."""
        if not context.has_role(ROLE_PORTFOLIO_AGGREGATOR):
            self._record_violation(context, "*", "cross_tenant_read")
            raise TenancyViolation(
                f"Tenant '{context.tenant_id}' lacks role '{ROLE_PORTFOLIO_AGGREGATOR}' "
                f"required for cross-tenant read"
            )

    def _record_violation(self, context: TenantContext, target: str, op: str) -> None:
        """Record a tenancy violation in the audit log."""
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            negotiation_id=None,
            agent_name="tenancy_enforcer",
            event_type=f"tenancy_violation_{op}",
            timestamp=datetime.now(timezone.utc),
            payload={
                "requesting_tenant": context.tenant_id,
                "target_tenant": target,
                "operation": op,
                "roles": list(context.roles),
            },
            severity="violation",
        ))
