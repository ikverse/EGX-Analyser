from datetime import date

from app.models import DailyPrice
from app.scoring import MAX_WINDOW_SESSIONS, Outcome, clamp_window, score


def session(day: int, high: float, low: float, close: float | None = None) -> DailyPrice:
    return DailyPrice(
        ticker="TEST",
        session_date=date(2026, 7, day),
        high=high,
        low=low,
        close=close if close is not None else (high + low) / 2,
    )


def test_target_one_is_reported_with_the_session_that_reached_it():
    result = score(
        [session(1, high=10.2, low=9.9), session(2, high=11.5, low=10.1)],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=12.0, stop_loss=9.5,
        window_sessions=10,
    )

    assert result.outcome is Outcome.TARGET_1
    assert result.settled_on == date(2026, 7, 2)
    assert result.sessions_elapsed == 2
    assert result.return_pct == 10.0


def test_the_further_target_wins_when_one_session_clears_both():
    result = score(
        [session(1, high=12.5, low=10.0)],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=12.0, stop_loss=9.5,
        window_sessions=10,
    )

    assert result.outcome is Outcome.TARGET_2


def test_a_session_that_hits_both_target_and_stop_is_ambiguous():
    """Daily figures cannot order intraday events, and guessing would flatter the hit rate."""
    result = score(
        [session(1, high=11.4, low=9.4)],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=12.0, stop_loss=9.5,
        window_sessions=10,
    )

    assert result.outcome is Outcome.AMBIGUOUS


def test_a_call_whose_entry_never_traded_is_not_counted_against_the_source():
    result = score(
        [session(1, high=9.0, low=8.5), session(2, high=8.9, low=8.2)],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.5,
        window_sessions=10,
    )

    assert result.outcome is Outcome.ENTRY_NOT_REACHED
    assert result.settled_on is None


def test_nothing_settles_inside_the_window_expires():
    days = [session(day, high=10.4, low=10.0) for day in range(1, 4)]

    result = score(
        days,
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.5,
        window_sessions=3,
    )

    assert result.outcome is Outcome.EXPIRED
    assert result.sessions_elapsed == 3


def test_sessions_beyond_the_window_are_ignored():
    """A target reached after the window closed must not count as a hit."""
    days = [session(1, high=10.4, low=10.0), session(2, high=10.5, low=10.1),
            session(3, high=99.0, low=10.2)]

    result = score(
        days,
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.5,
        window_sessions=2,
    )

    assert result.outcome is Outcome.EXPIRED


def test_a_stock_with_no_stored_sessions_is_unpriced_rather_than_missed():
    result = score(
        [], entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.5,
        window_sessions=10,
    )

    assert result.outcome is Outcome.UNPRICED


def test_the_window_is_held_between_one_and_thirty_sessions():
    assert clamp_window(0) == 1
    assert clamp_window(-5) == 1
    assert clamp_window(31) == MAX_WINDOW_SESSIONS
    assert clamp_window(10) == 10


def test_peak_high_reports_how_close_a_missed_call_came():
    result = score(
        [session(1, high=10.8, low=10.0)],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.5,
        window_sessions=1,
    )

    assert result.outcome is Outcome.EXPIRED
    assert result.peak_high == 10.8
