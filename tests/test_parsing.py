"""Offline tests against recorded portal responses. No network access."""
from pathlib import Path

from handelsregister_cli.dk import _extract_viewstate, parse_partial_nodes
from handelsregister_cli.portal import parse_doc_links, parse_search_results

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH_HTML = (FIXTURES / "search_results.html").read_text()
DK_PARTIAL = (FIXTURES / "dk_partial_expand.xml").read_text()


def test_parse_search_results():
    hits = parse_search_results(SEARCH_HTML)
    assert len(hits) == 2
    first = hits[0]
    assert first.name == "arcneo GmbH"
    assert first.index == 0
    assert first.register_num == "HRB 261478"
    assert first.state == "Berlin"
    assert "AD" in first.doc_labels and "DK" in first.doc_labels


def test_parse_doc_links_direct_and_dk():
    links = parse_doc_links(SEARCH_HTML, 0)
    # direct download link: no extra params
    ad_id, ad_extra = links["AD"]
    assert ad_id.startswith("ergebnissForm:selectedSuchErgebnisFormTable:0:")
    assert ad_extra == {}
    # DK link carries the Dokumentart property from its onclick handler
    _, dk_extra = links["DK"]
    assert dk_extra["property"] == "Global.Dokumentart.DK"
    assert dk_extra["property2"] == ""


def test_parse_doc_links_rows_are_independent():
    assert parse_doc_links(SEARCH_HTML, 0).keys() == parse_doc_links(SEARCH_HTML, 1).keys()
    ad0, _ = parse_doc_links(SEARCH_HTML, 0)["AD"]
    ad1, _ = parse_doc_links(SEARCH_HTML, 1)["AD"]
    assert ad0 != ad1


def test_parse_partial_nodes_reads_cdata():
    nodes = parse_partial_nodes(DK_PARTIAL)
    assert [n.rowkey for n in nodes] == ["0_0", "0_1"]
    assert nodes[0].label == "Dokumente zur Registernummer"
    assert nodes[0].leaf is False
    assert nodes[1].leaf is True
    assert "Gesellschafter" in nodes[1].label


def test_extract_viewstate():
    assert _extract_viewstate(DK_PARTIAL) == "8320053560402606116:-2884620046521278132"
