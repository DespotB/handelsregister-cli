"""Tests for filename sanitising and checksum dedupe."""
from handelsregister_cli.files import FileSink, clean_label, guess_extension, looks_like_document

PDF_A = b"%PDF-1.4 aaaa"
PDF_B = b"%PDF-1.4 bbbb"


def test_looks_like_document():
    assert looks_like_document(PDF_A)
    assert looks_like_document(b"PK\x03\x04zip")
    assert looks_like_document(b"<?xml version='1.0'?>")
    assert not looks_like_document(b"<!DOCTYPE html><html>")


def test_guess_extension():
    assert guess_extension(PDF_A) == ".pdf"
    assert guess_extension(b"<?xml ...") == ".xml"


def test_clean_label():
    assert (
        clean_label("Gesellschaftsvertrag / Satzung / Statut vom 29.09.2025")
        == "Gesellschaftsvertrag - Satzung - Statut vom 29.09.2025"
    )
    assert clean_label('a\\b:c*d?e"f<g>h|i') == "a-b-c-d-e-f-g-h-i"


def test_sink_dedupes_identical_content(tmp_path):
    sink = FileSink(tmp_path)
    assert sink.write("Anmeldung vom 26.02.2024", PDF_A, "dk:0_0_1") is not None
    # same bytes under another tree node -> skipped
    assert sink.write("Anmeldung vom 26.02.2024", PDF_A, "dk:0_0_5_0") is None
    assert len(list(tmp_path.glob("*.pdf"))) == 1


def test_sink_suffixes_name_collisions(tmp_path):
    sink = FileSink(tmp_path)
    d1 = sink.write("Einwilligung vom 11.03.2026", PDF_A, "dk:a")
    d2 = sink.write("Einwilligung vom 11.03.2026", PDF_B, "dk:b")
    assert d1.path.name == "Einwilligung vom 11.03.2026.pdf"
    assert d2.path.name == "Einwilligung vom 11.03.2026 (2).pdf"
