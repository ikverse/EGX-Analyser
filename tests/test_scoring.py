import pytest
from datetime import date, datetime, timezone

from app.models import DailyPrice
from app.scoring import MAX_WINDOW_SESSIONS, Outcome, clamp_window, score


def session(
    day: int, high: float, low: float, close: float | None = None, open: float | None = None,
) -> DailyPrice:
    # Opens at the session low unless a test says otherwise, so the entry is buyable at the open
    # and cases that are not about entry ordering stay unaffected.
    return DailyPrice(
        ticker="TEST",
        session_date=date(2026, 7, day),
        open=low if open is None else open,
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
    # Measured from the middle of the 10.0-10.2 band rather than its bottom.
    assert result.return_pct == 8.91


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


def test_repeating_a_session_corrects_it_rather_than_adding_a_second():
    """
    Yahoo dates each session, so re-running a backfill overwrites rather than duplicating.

    A duplicated session would let one day's high count twice and would shift every later session
    inside the window, so this is the property the whole scorecard rests on.
    """
    import asyncio

    from app.scoring import _upsert

    class FakeSession:
        def __init__(self) -> None:
            self.rows: list[DailyPrice] = []

        async def scalar(self, _statement):
            return self.rows[0] if self.rows else None

        def add(self, row):
            self.rows.append(row)

    fake = FakeSession()
    day = {"session_date": date(2026, 7, 28), "high": 10.0, "low": 9.0, "close": 9.5,
           "volume": 100, "source": "Yahoo Finance"}

    asyncio.run(_upsert(fake, "TEST", day))
    asyncio.run(_upsert(fake, "TEST", {**day, "high": 11.0}))

    assert len(fake.rows) == 1
    assert fake.rows[0].high == 11.0


def test_the_same_stock_quoted_two_ways_is_one_ticker():
    """
    Sources write both AMOC and AMOC.CA. Treating those as two stocks splits a channel's record
    and leaves one half unpriced, so every rate built on it is wrong.
    """
    from app.scoring import normalize_ticker

    assert normalize_ticker("AMOC.CA") == "AMOC"
    assert normalize_ticker(" amoc.ca ") == "AMOC"
    assert normalize_ticker("AMOC") == "AMOC"
    assert normalize_ticker(None) == ""


def test_entry_and_target_in_one_session_count_when_it_opened_inside_the_band():
    """The open precedes every other price, so the entry was available before the day's high."""
    result = score(
        [session(1, high=12.5, low=9.5, open=10.1)],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.0,
        window_sessions=10,
    )

    assert result.outcome is Outcome.TARGET_1


def test_entry_and_target_in_one_session_are_ambiguous_when_it_opened_above_the_band():
    """The stock may have run to the target first and only fallen back into the band afterwards."""
    result = score(
        [session(1, high=12.5, low=9.5, open=11.8)],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.0,
        window_sessions=10,
    )

    assert result.outcome is Outcome.AMBIGUOUS
    assert result.return_pct is None


def test_a_session_with_no_recorded_open_is_not_assumed_favourable():
    day = session(1, high=12.5, low=9.5)
    day.open = None

    result = score(
        [day],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.0,
        window_sessions=10,
    )

    assert result.outcome is Outcome.AMBIGUOUS


def test_entering_on_an_earlier_session_leaves_a_later_target_unaffected():
    result = score(
        [session(1, high=10.2, low=9.9), session(2, high=12.5, low=11.0)],
        entry_low=10.0, entry_high=10.2, target_1=11.0, target_2=None, stop_loss=9.0,
        window_sessions=10,
    )

    assert result.outcome is Outcome.TARGET_1
    assert result.sessions_elapsed == 2


def test_only_the_target_session_is_accepted():
    """A source belongs to the session printed on it, and to no other."""
    from datetime import date

    from app import source_date_gate

    target = date(2026, 7, 30)
    assert source_date_gate.accepts("30 JULY 2026", target)
    assert source_date_gate.accepts("30/7/2026", target)
    assert source_date_gate.accepts("30-Jul-2026", target)
    # The session before: a call made on the 29th for the 29th.
    assert not source_date_gate.accepts("29/07/2026", target)
    # The session after: the T+1 card, which belongs to the next report and not to two of them.
    assert not source_date_gate.accepts("31/7/2026", target)
    # A re-posted screenshot of an old card.
    assert not source_date_gate.accepts("13/7/2026", target)


def test_a_date_that_cannot_be_read_is_rejected():
    from datetime import date

    from app import source_date_gate

    target = date(2026, 7, 30)
    for value in (None, "", "last week", "سعر السهم"):
        assert not source_date_gate.accepts(value, target)


def test_dates_are_read_the_way_sources_print_them():
    from datetime import date

    from app import source_date_gate

    assert source_date_gate.parse("13/7/2026") == date(2026, 7, 13)
    assert source_date_gate.parse("2026-07-30") == date(2026, 7, 30)
    assert source_date_gate.parse("30 JULY 2026") == date(2026, 7, 30)
    assert source_date_gate.parse("٢٨ يوليو ٢٠٢٦") == date(2026, 7, 28)
    assert source_date_gate.parse("32/7/2026") is None
    assert source_date_gate.parse("30/13/2026") is None


def test_symbol_map_reads_both_series_across_the_migration():
    """Yahoo froze SYMBOL.CA on 29 July 2026, so one form alone leaves a hole from the 30th on."""
    from app.symbol_map import feeds_for

    assert feeds_for("ARAB") == ["EGS694A1C018.CA", "ARAB.CA"]
    assert feeds_for("arab.ca") == ["EGS694A1C018.CA", "ARAB.CA"]
    # A stock with no mapping still gets its legacy symbol rather than nothing.
    assert feeds_for("NOSUCH") == ["NOSUCH.CA"]
    assert feeds_for("") == []


class _FakeReport:
    """A saved analysis, as _unique_calls reads one."""

    def __init__(self, report_id, target_date, channels, rows):
        self.id = report_id
        self.report_date = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        self.summary = {
            "analysis_result": True,
            "target_date": target_date,
            "selected_channels": channels,
            "stock_source_table": rows,
        }


def _call_row(ticker, channel, target_1):
    return {
        "ticker": ticker, "company": ticker, "source": channel,
        "visible_source_date": "2026-07-30",
        "buy_price_low": 10.0, "buy_price_high": 10.5, "target_1": target_1, "stop_loss": 9.5,
    }


@pytest.mark.asyncio
async def test_a_later_run_replaces_the_channel_it_covered(monkeypatch):
    from app import insights

    reports = [
        _FakeReport(1, "2026-07-30", ["Alpha"], [_call_row("COMI", "Alpha", 12.0)]),
        _FakeReport(2, "2026-07-30", ["Alpha"], [_call_row("COMI", "Alpha", 13.0)]),
    ]

    async def fake_reports_since(_session, _since):
        return reports

    monkeypatch.setattr(insights, "_reports_since", fake_reports_since)
    calls = await insights._unique_calls(None, date(2026, 7, 1))

    assert len(calls) == 1
    assert calls[0]["target"] == 13.0


@pytest.mark.asyncio
async def test_a_later_narrower_run_does_not_erase_a_channel_it_never_looked_at(monkeypatch):
    """
    A run over fewer chats has nothing to say about a channel it never examined.

    Keeping whichever copy listed the most price levels let it win anyway, silently replacing
    scoring that had not been re-read.
    """
    from app import insights

    reports = [
        _FakeReport(1, "2026-07-30", ["Alpha", "Beta"], [
            _call_row("COMI", "Alpha", 12.0), _call_row("SCEM", "Beta", 20.0),
        ]),
        _FakeReport(2, "2026-07-30", ["Alpha"], [_call_row("COMI", "Alpha", 13.0)]),
    ]

    async def fake_reports_since(_session, _since):
        return reports

    monkeypatch.setattr(insights, "_reports_since", fake_reports_since)
    calls = {call["channel"]: call for call in await insights._unique_calls(None, date(2026, 7, 1))}

    assert calls["Alpha"]["target"] == 13.0
    assert calls["Beta"]["target"] == 20.0


@pytest.mark.asyncio
async def test_a_row_from_a_channel_the_run_did_not_cover_is_ignored(monkeypatch):
    """A run can only speak for the chats it was pointed at."""
    from app import insights

    reports = [_FakeReport(1, "2026-07-30", ["Alpha"], [
        _call_row("COMI", "Alpha", 12.0), _call_row("SCEM", "Gamma", 20.0),
    ])]

    async def fake_reports_since(_session, _since):
        return reports

    monkeypatch.setattr(insights, "_reports_since", fake_reports_since)
    calls = await insights._unique_calls(None, date(2026, 7, 1))

    assert [call["channel"] for call in calls] == ["Alpha"]


@pytest.mark.asyncio
async def test_a_report_without_a_recorded_coverage_falls_back_to_its_own_rows(monkeypatch):
    """Reports saved before coverage was recorded still count for what they do show."""
    from app import insights

    older = _FakeReport(1, "2026-07-30", [], [_call_row("COMI", "Alpha", 12.0)])
    older.summary.pop("selected_channels")

    async def fake_reports_since(_session, _since):
        return [older]

    monkeypatch.setattr(insights, "_reports_since", fake_reports_since)
    calls = await insights._unique_calls(None, date(2026, 7, 1))

    assert [call["channel"] for call in calls] == ["Alpha"]

