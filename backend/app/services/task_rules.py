"""Task rules: what the case matcher does to a Case's task at the end of each sweep, from the Case's state.

Run after every case's confidence word has been recomputed as of the sweep
time `now` (the run's clock), so a replay produces the tasks that would have
existed at each moment.

    R1  the Case has fresh support (single_source or corroborated) and no active
        task -> create a pending task. Kind: reach_block for a zone Case,
        welfare_check for a household Case. Pending = waiting for a person to
        assign it; nothing is ever dispatched automatically.
        After a person closed the Case's last task (complete, unable_to_reach,
        cancelled), R1 creates a new one only on NEW supporting evidence: first
        observed after that close. Evidence the engine merely keeps
        re-confirming (a block still cut off) does not count, or every close
        would be undone on the next sweep; a person can open a follow-up task.
    R2  the Case becomes corroborated -> set cases.escalated_at (once); the
        task's priority is recomputed.
    R3  the Case goes stale_verify (no fresh support, or the latest evidence
        contradicts it) -> flag the task verify_before_dispatch, with why.
    R4  an independent source contradicts the Case (today: the nominated
        neighbor's SEEN_OK) -> flag verify_before_dispatch, whatever evidence
        is more recent. A conflict between sources needs a person before
        anyone is sent; the household's own silence re-confirming every sweep
        must not hide it.
    R3b the Case has fresh support again and no R4 conflict stands -> clear
        the flag. An R4 flag is only cleared by a person.

A person clearing the flag (verify_cleared_at) is respected: R3 and R4 flag
again only on evidence newer than that. Evidence never completes or cancels a
task; only a person does. Every change is recorded as a TaskEvent snapshot.

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
from app.models.case_engine_contribution import ContributionDirection, Engine
from app.models.household import AgeBracket
from app.models.task import ACTIVE_STATUSES, TaskKind, TaskPriority, TaskStatus
from app.services.confidence import CaseConfidence, latest_evidence, visible

ENGINE_ACTOR = "engine:case_matcher"
FRESH_WORDS = (ConfidenceWord.single_source, ConfidenceWord.corroborated)
# Contradicting evidence from a source independent of the Case's own engines. The listening engine's only
# contradicting contribution is the nominated neighbor's SEEN_OK.
INDEPENDENT_CONTRADICTION_ENGINES = (Engine.listening,)


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


def _text(contribution) -> str:
    return contribution.rule_fragment.split("] ", 1)[-1][:160]


def _flag(case: Case, word: ConfidenceWord, now: datetime, cleared_at: Optional[datetime]) -> Optional[tuple[str, str]]:
    """(rule, reason) if the task should be flagged verify_before_dispatch as of `now`, else None."""
    def newer(t: datetime) -> bool:
        return cleared_at is None or t > cleared_at

    conflicts = [c for c in case.contributions if visible(c, now) and c.direction == ContributionDirection.contradicts
                 and c.engine in INDEPENDENT_CONTRADICTION_ENGINES]
    if conflicts:
        newest = max(conflicts, key=lambda c: c.first_observed_at)
        if newer(newest.first_observed_at):
            return "R4", f"an independent source contradicts the Case ({newest.engine.value}: {_text(newest)})"
    if word == ConfidenceWord.stale_verify:
        latest = latest_evidence(case, now)
        if latest is not None and latest.direction == ContributionDirection.contradicts:
            if newer(min(latest.observed_at, now)):
                return "R3", f"latest evidence contradicts the Case ({latest.engine.value}: {_text(latest)})"
        elif newer(now if latest is None else min(latest.observed_at, now)):
            return "R3", "no supporting evidence is fresh any more"
    return None


def _new_evidence_since(case: Case, since: datetime, now: datetime) -> bool:
    return any(c.direction == ContributionDirection.supports and visible(c, now) and c.first_observed_at > since
               for c in case.contributions)


def snapshot(task: Task, at: datetime, note: str, actor: str = ENGINE_ACTOR) -> None:
    task.events.append(TaskEvent(at=at, status=task.status, priority=task.priority,
                                 verify_before_dispatch=task.verify_before_dispatch,
                                 assigned_responder_id=task.assigned_responder_id, actor=actor, note=note))


def apply_task_rules(case: Case, conf: CaseConfidence, now: datetime, urgent: Optional[str] = None,
                     household: Optional[Household] = None) -> Optional[str]:
    """Apply R1-R4 to one Case as of `now`. Returns "created", "changed" or None."""
    word = conf.word
    task = case.task if case.task is not None and case.task.status in ACTIVE_STATUSES else None
    notes, created = [], False

    if task is None:
        if word not in FRESH_WORDS:
            return None
        closed = [t.completed_at for t in case.tasks if t.status not in ACTIVE_STATUSES and t.completed_at]
        if closed and not _new_evidence_since(case, max(closed), now):
            return None  # a person closed the last task; only new evidence reopens work
        priority, reason = _priority(word, False, urgent, household)
        task = Task(case=case, status=TaskStatus.pending, verify_before_dispatch=False,
                    kind=TaskKind.welfare_check if case.household_id else TaskKind.reach_block,
                    priority=priority, priority_reason=reason,
                    created_by_rule=f"R1: Case has fresh support ({word.value})"
                                    + (" after its last task closed" if closed else ""),
                    created_at=now)
        case.task = task
        created = True
        notes.append(f"created by {task.created_by_rule[:2]} ({word.value}); pending, awaiting assignment")

    if word == ConfidenceWord.corroborated and case.escalated_at is None:
        case.escalated_at = now
        notes.append("R2: Case corroborated, escalated")
    flag = _flag(case, word, now, task.verify_cleared_at)
    if flag is not None and not task.verify_before_dispatch:
        task.verify_before_dispatch, task.verify_reason = True, flag[1]
        notes.append(f"{flag[0]}: verify before dispatch: {flag[1]}")
    elif flag is None and task.verify_before_dispatch and word in FRESH_WORDS:
        task.verify_before_dispatch, task.verify_reason = False, None
        notes.append(f"R3b: evidence fresh again ({word.value})")
    priority, reason = _priority(word, task.verify_before_dispatch, urgent, household)
    if (priority, reason) != (task.priority, task.priority_reason):
        if not created:
            notes.append(f"priority {task.priority.value} -> {priority.value}: {reason}" if priority != task.priority
                         else f"priority {priority.value}, now because: {reason}")
        task.priority, task.priority_reason = priority, reason
    if not notes:
        return None
    snapshot(task, now, "; ".join(notes))
    return "created" if created else "changed"
