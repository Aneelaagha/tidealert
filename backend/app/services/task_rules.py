"""Task rules: what the case matcher does to a Case's task at the end of each sweep, from the Case's state.

Run after every case's confidence word has been recomputed as of the sweep
time `now` (the run's clock), so a replay produces the tasks that would have
existed at each moment.

    R1  the Case has fresh support (single_source or corroborated) and no active
        task -> create a pending task. Kind: reach_block for a zone Case,
        welfare_check for a household Case. Pending = waiting for a person to
        assign it; nothing is ever dispatched automatically.
    R2  the Case becomes corroborated -> set cases.escalated_at (once); the
        task's priority is recomputed.
    R3  the Case goes stale_verify (no fresh support, or the latest evidence
        contradicts it) -> flag the task verify_before_dispatch, with why.
    R3b the Case has fresh support again (e.g. a block isolated again) -> clear
        the flag.

Evidence never completes or cancels a task; only a person does. Every change
is recorded as a TaskEvent snapshot.

Priority (ordinal; a design choice, not calibrated against outcomes):
    low     verify_before_dispatch is set
    high    the Case is corroborated, or a household asked for help, or its
            nominated neighbor reported trouble
    medium  otherwise (one source)
    medium -> high for a household that is 65+ or has a disability. Those
            fields exist but hold only synthetic values so far.
"""
from datetime import datetime
from typing import Optional

from app.models import Case, Household, Task, TaskEvent
from app.models.case import ConfidenceWord
from app.models.case_engine_contribution import ContributionDirection
from app.models.household import AgeBracket
from app.models.task import ACTIVE_STATUSES, TaskKind, TaskPriority, TaskStatus
from app.services.confidence import CaseConfidence, latest_evidence

ENGINE_ACTOR = "engine:case_matcher"
FRESH_WORDS = (ConfidenceWord.single_source, ConfidenceWord.corroborated)


def _priority(word: ConfidenceWord, verify: bool, urgent: Optional[str],
              household: Optional[Household]) -> tuple[TaskPriority, str]:
    if verify:
        return TaskPriority.low, "evidence stale or contradicted: verify before dispatch"
    if word == ConfidenceWord.corroborated:
        priority, reason = TaskPriority.high, "Case corroborated by two independent sources"
    elif urgent:
        priority, reason = TaskPriority.high, urgent
    else:
        priority, reason = TaskPriority.medium, "one source"
    if priority == TaskPriority.medium and household is not None and (
            household.age_bracket == AgeBracket.age_65_plus or household.has_disability):
        priority, reason = TaskPriority.high, "one source; household is 65+ or has a disability (design choice)"
    return priority, reason


def _verify_reason(case: Case, now: datetime) -> str:
    latest = latest_evidence(case, now)
    if latest is not None and latest.direction == ContributionDirection.contradicts:
        text = latest.rule_fragment.split("] ", 1)[-1]
        return f"latest evidence contradicts the Case ({latest.engine.value}: {text[:160]})"
    return "no supporting evidence is fresh any more"


def _snapshot(task: Task, now: datetime, note: str) -> None:
    task.events.append(TaskEvent(at=now, status=task.status, priority=task.priority,
                                 verify_before_dispatch=task.verify_before_dispatch,
                                 assigned_responder_id=task.assigned_responder_id, actor=ENGINE_ACTOR, note=note))


def apply_task_rules(case: Case, conf: CaseConfidence, now: datetime, urgent: Optional[str] = None,
                     household: Optional[Household] = None) -> Optional[str]:
    """Apply R1-R3b to one Case as of `now`. Returns "created", "changed" or None."""
    word = conf.word
    task = case.task if case.task is not None and case.task.status in ACTIVE_STATUSES else None

    if task is None:
        if word not in FRESH_WORDS:
            return None
        priority, reason = _priority(word, False, urgent, household)
        task = Task(case=case, status=TaskStatus.pending, verify_before_dispatch=False,
                    kind=TaskKind.welfare_check if case.household_id else TaskKind.reach_block,
                    priority=priority, priority_reason=reason, created_by_rule=f"R1: Case has fresh support ({word.value})",
                    created_at=now)
        case.task = task
        if word == ConfidenceWord.corroborated and case.escalated_at is None:
            case.escalated_at = now
        _snapshot(task, now, f"created by R1 ({word.value}); pending, awaiting assignment")
        return "created"

    notes = []
    if word == ConfidenceWord.corroborated and case.escalated_at is None:
        case.escalated_at = now
        notes.append("R2: Case corroborated, escalated")
    if word == ConfidenceWord.stale_verify and not task.verify_before_dispatch:
        task.verify_before_dispatch, task.verify_reason = True, _verify_reason(case, now)
        notes.append(f"R3: verify before dispatch: {task.verify_reason}")
    elif word in FRESH_WORDS and task.verify_before_dispatch:
        task.verify_before_dispatch, task.verify_reason = False, None
        notes.append(f"R3b: evidence fresh again ({word.value})")
    priority, reason = _priority(word, task.verify_before_dispatch, urgent, household)
    if (priority, reason) != (task.priority, task.priority_reason):
        notes.append(f"priority {task.priority.value} -> {priority.value}: {reason}" if priority != task.priority
                     else f"priority {priority.value}, now because: {reason}")
        task.priority, task.priority_reason = priority, reason
    if not notes:
        return None
    _snapshot(task, now, "; ".join(notes))
    return "changed"
