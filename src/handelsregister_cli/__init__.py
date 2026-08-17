"""handelsregister-cli — search the German commercial register and download
registry documents (Handelsregisterauszug, Gesellschafterliste,
Gesellschaftsvertrag, …) from https://www.handelsregister.de.

Library quickstart::

    from handelsregister_cli import Portal
    from handelsregister_cli.files import FileSink, looks_like_document

    portal = Portal("arcneo GmbH")
    hits = portal.search()
    pdf = portal.fetch_direct(hits[0].index, "AD")   # current printout

    dk = portal.open_dk(hits[0].index)               # document folder
    for node in dk.walk_tree().values():
        if node.leaf and "Gesellschafter" in node.label:
            data = dk.download_leaf(node.rowkey)

The ``hreg`` CLI (see ``handelsregister_cli.cli``) wraps this with output
directories, checksum dedupe and a manifest.
"""
from .models import CompanyHit, Download, TreeNode
from .portal import Portal, PortalError

__version__ = "0.1.0"

__all__ = ["CompanyHit", "Download", "Portal", "PortalError", "TreeNode", "__version__"]
