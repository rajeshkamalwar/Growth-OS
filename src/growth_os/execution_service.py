from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from growth_os.api.errors import ConflictError, InvalidStateTransitionError, NotFoundError
from growth_os.db.models import (
    ActionProposal,
    ApprovalDecision,
    ApprovalDecisionValue,
    AuditEvent,
    ExecutionJob,
    ExecutionRun,
    ProposalStatus,
    RiskLevel,
    Workspace,
)
from growth_os.execution import ExecutionStatus
from growth_os.execution_repository import ExecutionOwned, ExecutionRepository
from growth_os.repositories import FoundationRepository, TenantContext
from growth_os.services import FoundationService


@dataclass(frozen=True)
class JobResult:
    job: ExecutionJob
    latest_run: ExecutionRun
    created: bool


class ExecutionService:
    def __init__(self, repository: ExecutionRepository) -> None:
        self.repository = repository

    async def create_job(
        self,
        context: TenantContext,
        *,
        workspace_id: UUID,
        kind: str,
        idempotency_key: str,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> JobResult:
        existing = await self.repository.get_job_by_idempotency_key(context, idempotency_key)
        if existing is not None:
            run = await self._required_run(context, existing.id)
            if (
                existing.workspace_id != workspace_id
                or existing.kind != kind
                or run.max_attempts != max_attempts
                or run.retry_delay_seconds != retry_delay_seconds
            ):
                raise ConflictError
            return JobResult(existing, run, False)

        foundation = FoundationService(FoundationRepository(self.repository.session))
        await foundation.get_owned(Workspace, context, workspace_id)
        job = ExecutionJob(
            tenant_id=context.tenant_id,
            workspace_id=workspace_id,
            kind=kind,
            idempotency_key=idempotency_key,
            status=ExecutionStatus.QUEUED,
        )
        run = ExecutionRun(
            tenant_id=context.tenant_id,
            job_id=job.id,
            status=ExecutionStatus.QUEUED,
            attempt_number=1,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
        audit = self._audit(context, "execution_job.created", "execution_job", job.id)
        self.repository.add_all(job, run, audit)
        await self._commit()
        await self.repository.refresh(job)
        await self.repository.refresh(run)
        return JobResult(job, run, True)

    async def get_job(self, context: TenantContext, job_id: UUID) -> JobResult:
        job = await self.get_owned(ExecutionJob, context, job_id)
        run = await self._required_run(context, job.id)
        return JobResult(job, run, False)

    async def create_proposal(
        self,
        context: TenantContext,
        *,
        job_id: UUID,
        action_type: str,
        description: str,
        risk_level: RiskLevel,
        requires_approval: bool,
    ) -> ActionProposal:
        await self.get_owned(ExecutionJob, context, job_id)
        if risk_level is RiskLevel.HIGH and not requires_approval:
            raise InvalidStateTransitionError("High-risk actions require explicit approval")
        proposal_status = (
            ProposalStatus.AWAITING_APPROVAL if requires_approval else ProposalStatus.APPROVED
        )
        proposal = ActionProposal(
            tenant_id=context.tenant_id,
            job_id=job_id,
            action_type=action_type,
            description=description,
            risk_level=risk_level,
            requires_approval=requires_approval,
            status=proposal_status,
        )
        audit = self._audit(context, "action_proposal.created", "action_proposal", proposal.id)
        self.repository.add_all(proposal, audit)
        await self._commit()
        await self.repository.refresh(proposal)
        return proposal

    async def decide_proposal(
        self,
        context: TenantContext,
        proposal_id: UUID,
        *,
        decision: ApprovalDecisionValue,
        decided_by: UUID,
        reason: str | None,
    ) -> ApprovalDecision:
        proposal = await self.get_owned(ActionProposal, context, proposal_id)
        if proposal.status is not ProposalStatus.AWAITING_APPROVAL:
            raise InvalidStateTransitionError("Proposal has already been finalized")
        proposal.status = ProposalStatus(decision.value)
        record = ApprovalDecision(
            tenant_id=context.tenant_id,
            proposal_id=proposal.id,
            decision=decision,
            decided_by=decided_by,
            reason=reason,
        )
        audit = self._audit(
            context,
            f"action_proposal.{decision.value}",
            "action_proposal",
            proposal.id,
            actor_id=decided_by,
            details={"decision_id": str(record.id)},
        )
        self.repository.add_all(proposal, record, audit)
        await self._commit(invalid_transition=True)
        await self.repository.refresh(record)
        return record

    async def get_owned(
        self, model: type[ExecutionOwned], context: TenantContext, resource_id: UUID
    ) -> ExecutionOwned:
        entity = await self.repository.get_owned(model, context, resource_id)
        if entity is None:
            raise NotFoundError
        return entity

    async def _required_run(self, context: TenantContext, job_id: UUID) -> ExecutionRun:
        run = await self.repository.latest_run(context, job_id)
        if run is None:
            raise NotFoundError
        return run

    async def _commit(self, *, invalid_transition: bool = False) -> None:
        try:
            await self.repository.commit()
        except IntegrityError as error:
            await self.repository.rollback()
            if invalid_transition:
                raise InvalidStateTransitionError("Proposal has already been finalized") from error
            raise ConflictError from error

    @staticmethod
    def _audit(
        context: TenantContext,
        event_type: str,
        resource_type: str,
        resource_id: UUID,
        *,
        actor_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            tenant_id=context.tenant_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            details=details or {},
        )
