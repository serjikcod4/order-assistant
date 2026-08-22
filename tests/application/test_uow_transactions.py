from order_assistant.application.drafts import DraftService
from order_assistant.application.submissions import ResilientOrderService
from order_assistant.application.workflow import process_extracted_order
from order_assistant.domain import DraftStatus, ERPFailureMode, ExtractedOrder, SubmissionStatus
from order_assistant.infrastructure.demo_data import demo_inventory
from order_assistant.infrastructure.erp import ResilientFakeERPClient
from order_assistant.infrastructure.repositories import InMemoryDraftRepository, InMemorySubmissionRepository
from order_assistant.infrastructure.unit_of_work import InMemoryUnitOfWorkFactory


class TrackingFactory:
    def __init__(self, factory):
        self.factory = factory; self.active_count = 0; self.events = []; self.commit_count = 0
    def __call__(self):
        parent, inner = self, self.factory()
        class Tracked:
            def __enter__(self):
                parent.active_count += 1; parent.events.append("uow_enter"); value = inner.__enter__(); self.drafts, self.submissions = value.drafts, value.submissions; return self
            def commit(self): parent.commit_count += 1; parent.events.append("uow_commit"); return inner.commit()
            def rollback(self): parent.events.append("uow_rollback"); return inner.rollback()
            def __exit__(self, *args):
                parent.active_count -= 1; parent.events.append("uow_exit"); return inner.__exit__(*args)
        return Tracked()


class TrackingERP(ResilientFakeERPClient):
    def __init__(self, tracking, *args): super().__init__(*args); self.tracking = tracking
    def create_order(self, draft, key):
        assert self.tracking.active_count == 0
        self.tracking.events.append("erp_create")
        return super().create_order(draft, key)
    def get_order_by_idempotency_key(self, key):
        assert self.tracking.active_count == 0
        self.tracking.events.append("erp_lookup")
        return super().get_order_by_idempotency_key(key)


def setup():
    drafts, submissions = InMemoryDraftRepository(), InMemorySubmissionRepository()
    tracking = TrackingFactory(InMemoryUnitOfWorkFactory(drafts, submissions))
    extracted = ExtractedOrder.model_validate({"model":"6204","quantity":500,"primary_brand":"SKF","fallback_brands":["FAG"],"max_unit_price":"250","delivery_deadline":"2026-08-15T09:00:00"})
    result = process_extracted_order(extracted, demo_inventory)
    draft_service = DraftService(tracking, ResilientFakeERPClient())
    draft = draft_service.create_draft(result); draft = draft_service.approve_draft(draft.draft_id, "manager")
    erp = TrackingERP(tracking)
    return drafts, submissions, tracking, erp, draft


def test_phase_a_commits_before_erp_and_phase_c_is_separate() -> None:
    drafts, submissions, tracking, erp, draft = setup()
    service = ResilientOrderService(tracking, erp)
    result = service.submit_approved_draft(draft.draft_id, "key")
    persisted = submissions.get(result.submission_id)
    assert result.status == SubmissionStatus.SUCCEEDED
    assert persisted.created_order_id == drafts.get(draft.draft_id).created_order_id
    assert tracking.events.index("erp_create") > tracking.events.index("uow_exit")
    assert tracking.commit_count >= 2


def test_crash_after_erp_leaves_pending_and_reconciliation_recovers(monkeypatch) -> None:
    drafts, submissions, tracking, erp, draft = setup()
    service = ResilientOrderService(tracking, erp)
    monkeypatch.setattr(service, "_success", lambda *args: (_ for _ in ()).throw(RuntimeError("crash")))
    try: service.submit_approved_draft(draft.draft_id, "key")
    except RuntimeError: pass
    pending = submissions.find_by_draft_id(draft.draft_id)
    assert pending.status == SubmissionStatus.PENDING and drafts.get(draft.draft_id).status == DraftStatus.APPROVED
    recovered = ResilientOrderService(tracking, erp).reconcile_submission(pending.submission_id)
    assert recovered.status == SubmissionStatus.SUCCEEDED and erp.actual_creation_count == 1


def test_timeout_and_retry_use_closed_uow_and_same_submission() -> None:
    drafts, submissions, tracking, erp, draft = setup(); erp.failure_mode = ERPFailureMode.TIMEOUT_BEFORE_CREATION
    service = ResilientOrderService(tracking, erp)
    unknown = service.submit_approved_draft(draft.draft_id, "key")
    erp.failure_mode = ERPFailureMode.SUCCESS
    retried = service.retry_submission(unknown.submission_id)
    assert unknown.status == SubmissionStatus.UNKNOWN
    assert retried.submission_id == unknown.submission_id and retried.attempt_count == 2
    assert erp.actual_creation_count == 1 and "erp_create" in tracking.events


def test_memory_uow_rollback_and_isolation() -> None:
    drafts, submissions, tracking, erp, draft = setup()
    factory = tracking.factory
    with factory() as first:
        changed = first.drafts.get(draft.draft_id); changed.status = DraftStatus.REJECTED; first.drafts.save(changed)
        with factory() as second: assert second.drafts.get(draft.draft_id).status == DraftStatus.APPROVED
        first.rollback()
    assert drafts.get(draft.draft_id).status == DraftStatus.APPROVED
