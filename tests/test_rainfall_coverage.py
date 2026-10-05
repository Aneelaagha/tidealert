"""The rainfall source's coverage check (no network): a window outside the source is refused with a clear
reason, so the pipeline can say rainfall is unavailable instead of crashing on an empty array."""
from datetime import datetime, timezone

import pytest

from app.services.rainfall import RainfallUnavailable, check_coverage

FIRST = datetime(1979, 2, 1, tzinfo=timezone.utc)
LAST = datetime(2020, 12, 31, 23, tzinfo=timezone.utc)  # the NWM v2.1 retrospective's last hour


def test_harvey_is_covered():
    check_coverage(datetime(2017, 8, 25, 4, tzinfo=timezone.utc), datetime(2017, 9, 3, 5, tzinfo=timezone.utc),
                   FIRST, LAST)


def test_helene_is_not_and_the_reason_names_the_coverage():
    with pytest.raises(RainfallUnavailable, match=r"covers 1979-02-01 \.\. 2020-12-31"):
        check_coverage(datetime(2024, 9, 25, 3, tzinfo=timezone.utc), datetime(2024, 10, 1, 4, tzinfo=timezone.utc),
                       FIRST, LAST)


def test_a_window_straddling_the_end_is_not_covered():
    with pytest.raises(RainfallUnavailable):
        check_coverage(datetime(2020, 12, 30, tzinfo=timezone.utc), datetime(2021, 1, 2, tzinfo=timezone.utc),
                       FIRST, LAST)
