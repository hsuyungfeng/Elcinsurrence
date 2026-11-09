import tempfile
import pytest

from elc_audit_engine.case_store.soap_draft_states import (
    ALL_DRAFT_STATES,
    STATE_APPROVED,
    STATE_DRAFT,
    STATE_FAILED,
    STATE_PUSHED,
    STATE_QUALITY_FAILED,
    STATE_QUEUED,
    STATE_REJECTED,
    STATE_VALIDATED,
    TERMINAL_DRAFT_STATES,
    IllegalDraftTransitionError,
    UnknownDraftStateError,
    assert_draft_transition_allowed,
    canonical_soap_text,
    compute_soap_content_hash,
    is_transition_allowed,
)
from elc_audit_engine.case_store.store import CaseNotFoundError, CaseStore


def test_draft_states_exhaustive():
    assert len(ALL_DRAFT_STATES) == 8
    assert len(TERMINAL_DRAFT_STATES) == 3

    # Unknown states
    with pytest.raises(UnknownDraftStateError):
        is_transition_allowed("nonexistent", STATE_VALIDATED)
    with pytest.raises(UnknownDraftStateError):
        is_transition_allowed(STATE_DRAFT, "nonexistent")

    # Valid transitions
    assert is_transition_allowed(STATE_DRAFT, STATE_VALIDATED)
    assert is_transition_allowed(STATE_DRAFT, STATE_QUALITY_FAILED)
    assert is_transition_allowed(STATE_VALIDATED, STATE_APPROVED)
    assert is_transition_allowed(STATE_VALIDATED, STATE_REJECTED)
    assert is_transition_allowed(STATE_APPROVED, STATE_QUEUED)
    assert is_transition_allowed(STATE_QUEUED, STATE_PUSHED)
    assert is_transition_allowed(STATE_QUEUED, STATE_FAILED)
    assert is_transition_allowed(STATE_FAILED, STATE_QUEUED)

    # Illegal transitions
    with pytest.raises(IllegalDraftTransitionError):
        assert_draft_transition_allowed(STATE_DRAFT, STATE_PUSHED)
    with pytest.raises(IllegalDraftTransitionError):
        assert_draft_transition_allowed(STATE_PUSHED, STATE_DRAFT)
    with pytest.raises(IllegalDraftTransitionError):
        assert_draft_transition_allowed(STATE_REJECTED, STATE_APPROVED)
    with pytest.raises(IllegalDraftTransitionError):
        assert_draft_transition_allowed(STATE_QUALITY_FAILED, STATE_APPROVED)


def test_canonical_soap_hash():
    soap1 = {"s": " Sore throat ", "o": "Pharynx injection\r\n", "a": "URI ", "p": "Medication\n"}
    soap2 = {"s": "Sore throat", "o": "Pharynx injection", "a": "URI", "p": "Medication"}
    assert compute_soap_content_hash(soap1) == compute_soap_content_hash(soap2)
    assert len(compute_soap_content_hash(soap1)) == 64


def test_casestore_soap_draft_lifecycle():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
        store = CaseStore(f.name)
        case_id = "CASE-101"
        soap = {"s": "Subjective complaint", "o": "Objective findings", "a": "Assessment J00", "p": "Plan rx"}

        # 1. Create draft
        draft = store.create_soap_draft(
            case_id=case_id,
            order_code="00109C",
            soap=soap,
            state=STATE_DRAFT,
            quality_score=90,
        )
        assert draft.state == STATE_DRAFT
        assert draft.version == 1
        assert draft.order_code == "00109C"
        assert len(draft.content_hash) == 64

        # 2. Transition draft -> validated
        v_draft = store.update_soap_draft_state(draft.draft_id, STATE_VALIDATED)
        assert v_draft.state == STATE_VALIDATED

        # 3. Edit draft -> new version (version 2)
        new_soap = dict(soap, s="Updated subjective complaint")
        e_draft = store.edit_soap_draft(draft.draft_id, new_soap, reviewer_id="dr_chen")
        assert e_draft.version == 2
        assert e_draft.state == STATE_VALIDATED
        assert e_draft.content_hash != draft.content_hash
        assert e_draft.reviewer_id == "dr_chen"

        # 4. Approve draft
        a_draft = store.update_soap_draft_state(draft.draft_id, STATE_APPROVED, reviewer_id="dr_chen", decision="approved")
        assert a_draft.state == STATE_APPROVED

        # 5. Queue draft
        q_draft = store.update_soap_draft_state(draft.draft_id, STATE_QUEUED)
        assert q_draft.state == STATE_QUEUED

        # 6. Push draft
        p_draft = store.update_soap_draft_state(draft.draft_id, STATE_PUSHED, agent_id="win-agent-1")
        assert p_draft.state == STATE_PUSHED
        assert p_draft.pushed_at is not None
        assert p_draft.agent_id == "win-agent-1"

        # 7. Check idempotency lookup
        found = store.find_pushed_soap_draft(case_id, e_draft.content_hash)
        assert found is not None
        assert found.draft_id == draft.draft_id

        # 8. Cannot transition from pushed (terminal)
        with pytest.raises(IllegalDraftTransitionError):
            store.update_soap_draft_state(draft.draft_id, STATE_APPROVED)


def test_agent_heartbeat():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
        store = CaseStore(f.name)
        store.record_agent_heartbeat("agent-01", version="1.0.0", his_status="ready")
        agents = store.list_agent_heartbeats()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "agent-01"
        assert agents[0]["is_online"] is True
