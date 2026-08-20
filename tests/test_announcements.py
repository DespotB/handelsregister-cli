"""Offline tests for the Registerbekanntmachungen parser and the watch diff logic."""
from pathlib import Path

from handelsregister_cli.announcements import (
    matches_keywords,
    parse_announcement_detail,
    parse_announcements,
    parse_remote_source,
)
from handelsregister_cli.watch import WatchState

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS_HTML = (FIXTURES / "announcements_results.html").read_text()
DETAIL_HTML = (FIXTURES / "announcement_detail.html").read_text()


def test_parse_announcements_all_rows():
    anns = parse_announcements(RESULTS_HTML)
    assert len(anns) == 6
    assert [a.date for a in anns] == ["20.08.2026"] * 3 + ["19.08.2026"] * 3


def test_parse_announcements_fields():
    first = parse_announcements(RESULTS_HTML)[0]
    assert first.id == "167692"
    assert first.js_date == "Thu Aug 20 00:00:00 CEST 2026"
    assert first.category == "Registerbekanntmachung nach dem Umwandlungsgesetz"
    assert first.state == "Bayern"
    assert first.court == "Amtsgericht München"
    assert first.register_num == "HRB 242458"
    assert first.name == "75cl Distribution GmbH"
    assert first.seat == "München"


def test_parse_announcements_hra_and_quoted_name():
    fourth = parse_announcements(RESULTS_HTML)[3]
    assert fourth.register_num == "HRA 1950"
    assert fourth.court == "Amtsgericht Berlin (Charlottenburg)"
    assert fourth.name.startswith('"Opernviertel"')


def test_parse_remote_source():
    assert parse_remote_source(RESULTS_HTML) == "bekanntMachungenForm:j_idt173"


def test_parse_announcement_detail():
    d = parse_announcement_detail(DETAIL_HTML)
    assert d["date"] == "20.08.2026"
    assert d["entry_date"] == "19.08.2026"
    assert d["category"] == "Registerbekanntmachung nach dem Umwandlungsgesetz"
    assert d["name"] == "75cl Distribution GmbH"
    assert d["legal_form"] == "Gesellschaft mit beschränkter Haftung"
    assert d["seat"] == "München"
    assert "Verschmelzung" in d["text"]


def test_matches_keywords_case_insensitive_on_name_seat_category():
    ann = parse_announcements(RESULTS_HTML)[0]
    assert matches_keywords(ann, ["distribution"])
    assert matches_keywords(ann, ["münchen"])
    assert matches_keywords(ann, ["umwandlungsgesetz"])
    assert not matches_keywords(ann, ["holding"])
    assert matches_keywords(ann, [])  # no keywords = match everything


def test_watch_state_first_run_seeds_silently(tmp_path):
    state = WatchState(tmp_path / "watch.json")
    anns = parse_announcements(RESULTS_HTML)
    assert state.new_announcements(anns) == []  # first run: seed only
    state.save()
    reloaded = WatchState(tmp_path / "watch.json")
    assert reloaded.new_announcements(anns) == []  # nothing new


def test_watch_state_reports_only_unseen(tmp_path):
    anns = parse_announcements(RESULTS_HTML)
    state = WatchState(tmp_path / "watch.json")
    state.new_announcements(anns[:4])
    state.save()
    reloaded = WatchState(tmp_path / "watch.json")
    fresh = reloaded.new_announcements(anns)
    assert [a.id for a in fresh] == [anns[4].id, anns[5].id]


def test_watch_state_search_diff(tmp_path):
    state = WatchState(tmp_path / "watch.json")
    assert state.new_search_hits("holding", [("HRB 1", "A GmbH"), ("HRB 2", "B GmbH")]) == []
    state.save()
    reloaded = WatchState(tmp_path / "watch.json")
    fresh = reloaded.new_search_hits("holding", [("HRB 1", "A GmbH"), ("HRB 3", "C Holding GmbH")])
    assert fresh == [("HRB 3", "C Holding GmbH")]
    # a different query has its own seen-set
    assert reloaded.new_search_hits("fintech", [("HRB 1", "A GmbH")]) == []


def test_normalize_date_accepts_both_formats():
    from handelsregister_cli.cli import normalize_date

    assert normalize_date("19.08.2026") == "19.08.2026"
    assert normalize_date("2026-08-19") == "19.08.2026"


def test_normalize_date_rejects_garbage():
    import pytest

    from handelsregister_cli.cli import normalize_date

    with pytest.raises(ValueError):
        normalize_date("gestern")


def test_parse_announcement_detail_without_entry_date():
    # Löschungsankündigungen carry no Eintragungsdatum block; fields must not shift.
    html = (FIXTURES / "announcement_detail_loeschung.html").read_text()
    d = parse_announcement_detail(html)
    assert d["date"] == "20.08.2026"
    assert d["category"] == "Löschungsankündigung"
    assert d["entry_date"] == ""
    assert d["name"] == "Hossy Bau GmbH"
    assert d["legal_form"] == "Gesellschaft mit beschränkter Haftung"
    assert d["seat"] == "Berlin"
    assert "Amtslöschungsverfahren" in d["text"]
