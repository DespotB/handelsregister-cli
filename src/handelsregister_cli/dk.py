"""DK (Dokumentenansicht) navigation: expand the PrimeFaces tree, download leaves.

The DK page hosts the substantive registry documents: shareholder lists
(Gesellschafterliste), articles of association (Gesellschaftsvertrag), founding
protocols, applications and consents. The tree loads lazily via PrimeFaces
partial AJAX; docs/DESIGN.md documents the wire format.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlencode

import mechanize
from bs4 import BeautifulSoup

from .models import TreeNode
from .portal import BASE_URL, PortalError

TREE_ID = "dk_form:dktree"


def parse_partial_nodes(xml: str) -> list[TreeNode]:
    """Extract tree nodes from a ``<partial-response>`` document.

    The rendered ``<li>`` markup sits inside a CDATA section of the
    ``<update id="dk_form:dktree...">`` element. An HTML parser applied to the
    whole XML drops CDATA content, so the payload is regex-extracted first and
    parsed as HTML on its own.
    """
    payload = "".join(
        re.findall(r'<update id="dk_form:dktree[^"]*"><!\[CDATA\[(.*?)\]\]></update>', xml, re.DOTALL)
    )
    soup = BeautifulSoup(payload, "html.parser")
    nodes = []
    for li in soup.select("li.ui-treenode"):
        rowkey = li.get("data-rowkey")
        if rowkey is None:
            continue
        label_el = li.select_one(".ui-treenode-label")
        nodes.append(
            TreeNode(
                rowkey=rowkey,
                label=label_el.get_text(" ", strip=True) if label_el else "",
                leaf="ui-treenode-leaf" in (li.get("class") or []),
            )
        )
    return nodes


def _extract_viewstate(xml: str) -> str:
    m = re.search(r"ViewState[^>]*><!\[CDATA\[(.*?)\]\]>", xml)
    return m.group(1) if m else ""


class DkSession:
    """A live DK page bound to one company; walks the tree and downloads leaves."""

    def __init__(self, browser: mechanize.Browser, page_html: str, delay: float = 3.0):
        self.browser = browser
        self.delay = delay
        soup = BeautifulSoup(page_html, "html.parser")
        form = soup.find("form", id="dk_form")
        if form is None:
            raise PortalError("DK page did not contain dk_form — portal layout changed?")
        action = form.get("action", "")
        self.action = BASE_URL + action if action.startswith("/") else action
        vs = form.find("input", {"name": "javax.faces.ViewState"})
        if vs is None:
            raise PortalError("no ViewState on DK page")
        self.viewstate = vs["value"]
        # The Download button id (dk_form:j_idt205 at the time of writing) is
        # JSF-generated and NOT stable across deployments — locate it by text.
        self.download_button = None
        for btn in form.find_all("button"):
            if "download" in btn.get_text(" ", strip=True).lower():
                self.download_button = btn.get("id")
                break
        if self.download_button is None:
            raise PortalError("no Download button found on DK page")
        # Format radio: false = single original file, true = ZIP.
        radio = form.find("input", {"type": "radio"})
        self.radio_name = radio.get("name") if radio else "dk_form:radio_dkbuttons"

    # -- wire helpers ------------------------------------------------------

    def _post(self, data: dict, ajax: bool) -> bytes:
        time.sleep(self.delay)
        req = mechanize.Request(self.action, data=urlencode(data))
        if ajax:
            req.add_header("Faces-Request", "partial/ajax")
            req.add_header("X-Requested-With", "XMLHttpRequest")
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        resp = self.browser.open(req)
        payload = resp.read()
        if ajax:
            new_vs = _extract_viewstate(payload.decode("utf-8", errors="replace"))
            if new_vs:
                self.viewstate = new_vs
        return payload

    def _tree_event(self, event: str, rowkey: str, render: str) -> str:
        data = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": TREE_ID,
            "javax.faces.partial.execute": TREE_ID,
            "javax.faces.partial.render": render,
            "javax.faces.behavior.event": event,
            "javax.faces.partial.event": event,
            f"{TREE_ID}_{'expandNode' if event == 'expand' else 'instantSelection'}": rowkey,
            "dk_form": "dk_form",
            f"{TREE_ID}_selection": rowkey if event == "select" else "",
            f"{TREE_ID}_scrollState": "0,0",
            "javax.faces.ViewState": self.viewstate,
        }
        return self._post(data, ajax=True).decode("utf-8", errors="replace")

    # -- public API --------------------------------------------------------

    def walk_tree(self) -> dict[str, TreeNode]:
        """Breadth-first expand the whole tree; returns ``{rowkey: TreeNode}``."""
        nodes: dict[str, TreeNode] = {}
        queue = ["0"]
        expanded = set()
        while queue:
            rowkey = queue.pop(0)
            if rowkey in expanded:
                continue
            expanded.add(rowkey)
            xml = self._tree_event("expand", rowkey, render=TREE_ID)
            for node in parse_partial_nodes(xml):
                if node.rowkey in nodes:
                    continue
                nodes[node.rowkey] = node
                if not node.leaf:
                    queue.append(node.rowkey)
        return nodes

    def download_leaf(self, rowkey: str) -> bytes:
        """Select a leaf node and press Download; returns the raw response body.

        Callers should verify the payload looks like a document
        (:func:`handelsregister_cli.files.looks_like_document`) — empty
        categories answer with an HTML page instead of a file.
        """
        self._tree_event(
            "select", rowkey, render="dk_form:detailsNodePanelGrid dk_form:dktree dk_formInfobox"
        )
        data = {
            "dk_form": "dk_form",
            f"{TREE_ID}_selection": rowkey,
            f"{TREE_ID}_scrollState": "0,0",
            self.radio_name: "false",
            self.download_button: "",
            "javax.faces.ViewState": self.viewstate,
        }
        return self._post(data, ajax=False)
