"""Case confidence at read time: time decay per engine, aggregation, and the confidence word.

Stored CaseEngineContribution.engine_confidence is the strength of the
evidence when it was last confirmed (observed_at), before any decay. Decay is
applied only when a case is read or aggregated, relative to `now`:

    effective = engine_confidence * 0.5 ** (age / HALF_LIFE[engine])
    age       = now - min(observed_at, now)

A contribution only exists from first_observed_at on. Between
first_observed_at and observed_at the engine was re-confirming it every
sweep, so a case read as of a time in that interval sees it at age 0. That
lets a finished run be read back at any earlier time; the value used is the
last confirmed engine_confidence (earlier values are not stored).

Procedural and neutral contributions always count 0. Half-lives follow how
fast each engine's evidence goes stale: a silence reading is about a
household right now and is refreshed every sweep while it holds; a flood
stage changes over hours.

Aggregation per case (noisy-or over contributions of each direction):

    support       = 1 - prod(1 - effective)   over "supports"
    contradiction = 1 - prod(1 - effective)   over "contradicts"

Confidence word:

- stale_verify:  no supporting contribution is still fresh (effective >= FRESH), or the most recent
                 evidence (supporting or contradicting) contradicts the case: it needs a human check
- corroborated:  fresh support from >= 2 independent sources: two engines, or one contribution
                 carrying >= 2 independent reports (e.g. depth reports from 2 households)
- single_source: otherwise

HALF_LIFE and FRESH are unvalidated design choices, not calibrated against
case outcomes (none are recorded yet).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models import Case, CaseEngineContribution
from app.models.case import ConfidenceWord
from app.models.case_engine_contribution import ContributionDirection, Engine

HALF_LIFE = {
    Engine.silence: timedelta(minutes=30),
    Engine.listening: timedelta(hours=2),
    Engine.isolation: timedelta(hours=3),
}
FRESH = 0.25  # effective confidence below which a supporting contribution no longer counts as fresh


def effective(contribution: CaseEngineContribution, now: datetime) -> float:
    """A contribution's confidence at `now`, after time decay; 0 for procedural and neutral ones."""
    if contribution.direction in (ContributionDirection.procedural, ContributionDirection.neutral):
        return 0.0
    age = max((now - _seen(contribution, now)).total_seconds(), 0.0)
    return contribution.engine_confidence * 0.5 ** (age / HALF_LIFE[contribution.engine].total_seconds())


def _seen(contribution: CaseEngineContribution, now: datetime) -> datetime:
    """When the contribution was last confirmed, as known at `now`."""
    return min(contribution.observed_at, now)


def visible(contribution: CaseEngineContribution, now: datetime) -> bool:
    """Whether the contribution existed at `now`."""
    return contribution.first_observed_at <= now


@dataclass
class CaseConfidence:
    support: float
    contradiction: float
    fresh_sources: int
    word: ConfidenceWord


def _noisy_or(values) -> float:
    miss = 1.0
    for v in values:
        miss *= 1.0 - v
    return 1.0 - miss


def case_confidence(case: Case, now: datetime) -> CaseConfidence:
    evidence = [c for c in case.contributions
                if c.direction in (ContributionDirection.supports, ContributionDirection.contradicts)
                and visible(c, now)]
    supports = [(c, effective(c, now)) for c in evidence if c.direction == ContributionDirection.supports]
    contradicts = [(c, effective(c, now)) for c in evidence if c.direction == ContributionDirection.contradicts]
    fresh = [c for c, e in supports if e >= FRESH]
    engines = {c.engine for c in fresh}
    fresh_sources = max(len(engines), max((c.independent_sources for c in fresh), default=0))
    latest = max(evidence, key=lambda c: _seen(c, now), default=None)
    if not fresh or (latest is not None and latest.direction == ContributionDirection.contradicts):
        word = ConfidenceWord.stale_verify
    elif fresh_sources >= 2:
        word = ConfidenceWord.corroborated
    else:
        word = ConfidenceWord.single_source
    return CaseConfidence(
        support=_noisy_or(e for _, e in supports),
        contradiction=_noisy_or(e for _, e in contradicts),
        fresh_sources=fresh_sources,
        word=word,
    )
