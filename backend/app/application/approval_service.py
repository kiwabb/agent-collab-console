from datetime import datetime
from uuid import uuid4

from app.domain.models import Approval, ApprovalEvent
from app.domain.states import SessionState


class ApprovalService:
    def __init__(self, session_service):
        self.session_service = session_service
        self.approvals: dict[str, Approval] = {}

    def _create_event(self, session, approval, event_type: str) -> ApprovalEvent:
        event = ApprovalEvent(
            id=str(uuid4()),
            session_id=session.id,
            task_id=approval.task_id,
            approval_id=approval.id,
            event_type=event_type,
            created_at=datetime.now(),
        )
        session.approval_events.append(event)
        return event

    async def request_submission(self, session_id: str, task_id: str) -> Approval:
        session = await self.session_service.get_session(session_id)
        session.state = SessionState.AWAITING_APPROVAL
        approval = Approval(
            id=str(uuid4()),
            session_id=session_id,
            task_id=task_id,
            action="submit_code",
            created_at=datetime.now(),
        )
        session.approvals.append(approval)
        self._create_event(session, approval, "requested")
        await self.session_service.update_session(session)
        self.approvals[approval.id] = approval
        return approval

    async def approve(self, approval_id: str) -> Approval:
        approval = self.approvals[approval_id]
        approval.status = "approved"
        session = await self.session_service.get_session(approval.session_id)
        session.state = SessionState.APPROVED
        self._create_event(session, approval, "approved")
        await self.session_service.update_session(session)
        return approval

    async def reject(self, approval_id: str) -> Approval:
        approval = self.approvals[approval_id]
        approval.status = "rejected"
        session = await self.session_service.get_session(approval.session_id)
        session.state = SessionState.IMPLEMENTING
        self._create_event(session, approval, "rejected")
        await self.session_service.update_session(session)
        return approval
