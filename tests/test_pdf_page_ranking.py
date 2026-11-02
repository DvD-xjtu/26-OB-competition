"""PDF retrieval keeps primary tables despite SEC navigation headers."""

import asyncio
import io
import re
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from powercontext.artifacts import ArtifactRef
from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document, search_pdf_pages


def test_navigation_header_does_not_exclude_financial_statement():
    reference = ArtifactRef(family="memory", artifact_id="memory", revision=1)
    texts = [
        "ACME_2025_10K\nTable of Contents\nConsolidated Statement of Income\nNet profit "
        + " ".join(str(i) for i in range(30)),
        *["ACME_2025_10K\nDiscussion of income earnings operating cash profitability " * 5 for _ in range(10)],
    ]
    hits = [
        SimpleNamespace(text=text, entry_id=str(i), entry_version_id="v1", memory_ref=reference)
        for i, text in enumerate(texts)
    ]

    class Memory:
        async def search(self, request):
            return SimpleNamespace(hits=[hit for hit in hits if request.query in hit.text.lower()])

    citations = asyncio.run(search_pdf_pages(Memory(), "What is ACME's operating income for 2025?", limit=3))
    assert len(citations) == 3
    assert "0" in [citation.entry_id for citation in citations]
    assert all(citation.memory_ref == reference for citation in citations)


def test_broken_cross_reference_is_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    damaged = re.sub(rb"startxref\s+\d+", b"startxref\n0", buffer.getvalue())
    with pytest.raises(ValueError, match="completely parse"):
        parse_pdf_document(PDFDocumentInput(document_id="broken", content=damaged))
