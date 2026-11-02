"""Complete PDF page capture and offline evidence-page retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections import Counter

from pydantic import BaseModel, Field, field_validator

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime.models import SearchMemoryRequest
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be blank")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1, strict=True)
    text: str

    @field_validator("document_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return PDFDocumentInput.validate_id(value)


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page, publishing nothing if extraction fails."""
    from pypdf import PdfReader

    try:
        if not value.content or b"%PDF-" not in value.content[:1024] or b"%%EOF" not in value.content[-4096:]:
            raise ValueError("incomplete PDF")  # noqa: TRY003
        reader = PdfReader(io.BytesIO(value.content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")  # noqa: TRY003
        digest = hashlib.sha256(value.content).hexdigest()
        return tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=page.extract_text() or "",
            )
            for number, page in enumerate(reader.pages, 1)
        )
    except Exception as exc:
        raise ValueError("could not completely parse PDF") from exc  # noqa: TRY003


class PDFPageSource(Source):
    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageAdapter:
    name = "pdf-page"
    input_class = PDFPageInput
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = json.dumps(
            [value.document_id, value.document_sha256, value.page_number], ensure_ascii=False, separators=(",", ":")
        ).encode()
        return PDFPageSource(
            name="pdf:" + hashlib.sha256(identity).hexdigest(),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(**{key: getattr(source, key) for key in PDFPageInput.model_fields})


class PDFPageProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(PDFPageAdapter(), version="1", projections=(PDFPageProjection(),))

_STOP = set(
    "a an the of for in on to and or as at by from is are was were be been has have had do does did "
    "what which how when where why who that this it its with their any can only use using shown "
    "give answer question respond response assuming perspective details calculate define reported "
    "not if then state directly explicitly outlined quantity unadjusted fy usd millions".split()
)
_EXPANSIONS = {
    "geographies": "geographic geography countries international segments operations markets",
    "geographic": "countries international segments operations markets",
    "legal": "litigation proceedings contingencies lawsuits",
    "battles": "litigation proceedings contingencies lawsuits",
    "ebitda": "operating income depreciation amortization cash flows",
    "capex": "capital expenditures property plant equipment purchases",
    "restructuring": "restructuring impairment charges",
    "income": "income earnings operations",
    "revenue": "revenue revenues sales",
    "margin": "income revenue revenues sales",
    "liquidity": "cash current assets liabilities",
    "dividend": "dividend dividends distributions",
    "assets": "assets balance sheets financial position",
    "liabilities": "liabilities balance sheets financial position",
    "equity": "equity shareholders stockholders balance sheets",
    "debt": "debt borrowings obligations balance sheets",
    "profit": "profit income earnings operations",
    "profits": "profit income earnings operations",
    "sales": "sales revenue revenues",
    "growth": "revenue revenues sales income",
    "cash": "cash flows operating investing financing",
    "return": "income equity assets",
    "ratio": "assets liabilities income equity",
    "repurchases": "repurchases shares stock treasury",
    "dividends": "dividends distributions stockholders",
    "operations": "operations segments business",
    "operates": "operations segments business geographic countries international",
}


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve lexical candidates and rank whole pages with financial query expansion."""
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be nonnegative")  # noqa: TRY003
    if limit == 0:
        return ()
    original = [token for token in re.findall(r"[a-z]+|\d+", question.lower()) if token not in _STOP]
    weights = {token: 1.0 for token in original}
    for token in original:
        for expanded in _EXPANSIONS.get(token, "").split():
            weights[expanded] = max(weights.get(expanded, 0), 0.65)
    hits = {}
    for token in weights:
        if token.isdigit() or len(token) < 3:
            continue
        result = await memory.search(SearchMemoryRequest(query=token, limit=2048, mode="fts"))
        for hit in result.hits:
            hits[(hit.entry_id, hit.entry_version_id)] = hit
    if not hits:
        return ()
    query_compact = re.sub(r"[^a-z0-9]", "", question.lower())
    named_documents = set()
    for hit in hits.values():
        document_id = hit.text.partition("\n")[0]
        company = re.split(r"[_ -](?:19|20)\d{2}", document_id.lower())[0]
        company_key = re.sub(r"[^a-z0-9]", "", company)
        if len(company_key) >= 2 and company_key in query_compact:
            named_documents.add(document_id)
    if named_documents:
        hits = {key: hit for key, hit in hits.items() if hit.text.partition("\n")[0] in named_documents}
    documents = [
        (hit, Counter(re.findall(r"[a-z]+|\d+", hit.text.partition("\n")[2].lower()))) for hit in hits.values()
    ]
    df = Counter(term for _, counts in documents for term in counts)
    average = sum(sum(counts.values()) for _, counts in documents) / len(documents)

    def score(pair):
        hit, counts = pair
        size = sum(counts.values())
        value = 0.0
        for term, weight in weights.items():
            frequency = counts[term]
            if frequency:
                idf = math.log(1 + (len(documents) - df[term] + 0.5) / (df[term] + 0.5))
                value += weight * idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * size / average))
        document_id, _, body = hit.text.partition("\n")
        company = re.split(r"[_\d]", document_id.lower())[0]
        if len(company) >= 3 and re.sub(r"[^a-z0-9]", "", company) in query_compact:
            value *= 2
        # Financial statement headings help distinguish primary tables from repeated narrative mentions.
        heading = body[:600].lower()
        if any(term in weights for term in ("income", "ebitda", "capex", "cash")):
            if re.search(r"(consolidated|combined)\s+statements?\s+of", heading):
                value *= 1.6
        return value

    ranked = sorted(documents, key=score, reverse=True)
    # Reserve a small portion for primary statement tables when the query asks for financial quantities.
    # A ratio or cash-flow question often requires complementary tables whose vocabulary differs.
    quantitative = {
        "income",
        "ebitda",
        "capex",
        "margin",
        "assets",
        "liabilities",
        "equity",
        "debt",
        "profit",
        "profits",
        "revenue",
        "revenues",
        "sales",
        "cash",
        "ratio",
        "dividends",
    }
    if quantitative.intersection(original):
        statements = []
        patterns = (
            r"(?:consolidated\s+)?(?:statements?\s+of\s+(?:income|operations|earnings)|income\s+statements?)",
            r"(?:consolidated\s+)?(?:statements?\s+of\s+cash\s+flows?|cash\s+flows?\s+statements?)",
            r"(?:consolidated\s+)?(?:balance\s+sheets?|statements?\s+of\s+financial\s+position)",
        )
        for pattern in patterns:
            matches = [pair for pair in ranked if re.search(pattern, pair[0].text.partition("\n")[2][:700].lower())]
            # Contents pages mention every statement; actual tables contain financial rows and numbers.
            matches = [
                pair
                for pair in matches
                if sum(count for term, count in pair[1].items() if term.isdigit()) >= 20
                and "table of contents" not in pair[0].text.partition("\n")[2][:700].lower()
            ]
            statements.extend(matches[:2])
        reserve = min(len(statements), max(1, limit // 3))
        ranked = ranked[: max(0, limit - reserve)] + statements[:reserve] + ranked[max(0, limit - reserve) :]
    citations = []
    seen = set()
    for hit, _ in ranked:
        # Source identities are revision-specific page identities, shared by duplicate observations.
        key = (
            tuple((source.source_type, source.source_id) for source in hit.sources)
            if hasattr(hit, "sources")
            else hit.entry_id
        )
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            MemoryCitation(memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id)
        )
        if len(citations) == limit:
            break
    return tuple(citations)
