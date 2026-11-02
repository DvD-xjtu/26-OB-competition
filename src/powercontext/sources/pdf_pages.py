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
            raise ValueError("incomplete PDF")  # noqa: TRY003, TRY301
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")  # noqa: TRY003, TRY301
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

_STOP = {
    "a",
    "an",
    "analyst",
    "and",
    "answer",
    "any",
    "are",
    "as",
    "assuming",
    "at",
    "based",
    "be",
    "been",
    "by",
    "calculate",
    "can",
    "companies",
    "company",
    "define",
    "details",
    "did",
    "directly",
    "do",
    "does",
    "explicitly",
    "fiscal",
    "following",
    "for",
    "from",
    "fy",
    "give",
    "had",
    "has",
    "have",
    "how",
    "if",
    "in",
    "investment",
    "is",
    "it",
    "its",
    "millions",
    "not",
    "of",
    "on",
    "only",
    "or",
    "outlined",
    "perspective",
    "quantity",
    "question",
    "relying",
    "reported",
    "respond",
    "response",
    "shown",
    "state",
    "statement",
    "statements",
    "that",
    "the",
    "their",
    "then",
    "this",
    "to",
    "unadjusted",
    "usd",
    "use",
    "using",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "year",
    "years",
}
_EXPANSIONS = {
    "geographies": "geographic geography countries international segments operations markets",
    "geographic": "countries international segments operations markets",
    "legal": "litigation proceedings contingencies lawsuits",
    "battles": "litigation proceedings contingencies lawsuits",
    "ebitda": "operating income depreciation amortization cash flows",
    "capex": "capital expenditures property plant equipment purchases",
    "restructuring": "restructuring impairment charges",
    "income": "income earnings operations profit",
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
    "operates": "operations segments divisions business geographic countries international",
    "geography": "geographic geographies segments divisions countries international",
    "ebit": "operating income profit earnings",
    "roa": "income assets balance sheets",
    "roe": "income equity stockholders shareholders",
    "cogs": "cost sales revenue",
    "employees": "employees employee workforce personnel",
    "headcount": "employees employee workforce personnel",
    "tax": "tax taxes provision income effective",
    "taxes": "tax taxes provision income effective",
    "working": "current assets liabilities",
    "gross": "gross profit cost sales revenue",
    "payout": "dividends income earnings",
    "repurchase": "repurchase repurchases shares stock treasury",
    "capital": "capital expenditures purchases property equipment",
    "expenditures": "expenditures purchases property equipment",
}


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve lexical candidates and rank whole pages with financial query expansion."""
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be nonnegative")  # noqa: TRY003
    if limit == 0:
        return ()
    original = [token for token in re.findall(r"[a-z]+|\d+", question.lower()) if token not in _STOP]
    weights = {token: 0.15 if token.isdigit() else 1.0 for token in original}
    if re.search(r"d\s*&\s*a", question.lower()):
        weights.update(depreciation=1.0, amortization=1.0)
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
    ranked = _rank_candidates(hits, question, original, weights, limit)
    return _page_citations(ranked, limit)


def _page_citations(ranked, limit):
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


def _rank_candidates(hits, question, original, weights, limit):
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
    if named_documents:
        # The company name identifies a document; its repeated page headers add no topic evidence.
        company_tokens = set()
        for document_id in named_documents:
            company_tokens.update(re.findall(r"[a-z]+", re.split(r"[_ -](?:19|20)\d{2}", document_id.lower())[0]))
        weights = {term: weight for term, weight in weights.items() if term not in company_tokens}
    documents = [
        (hit, Counter(re.findall(r"[a-z]+|\d+", hit.text.partition("\n")[2].lower()))) for hit in hits.values()
    ]
    df = Counter(term for _, counts in documents for term in counts)
    average = sum(sum(counts.values()) for _, counts in documents) / len(documents)

    ranked = sorted(
        documents,
        key=lambda pair: _score_page(pair, weights, df, average, len(documents), original, query_compact),
        reverse=True,
    )
    return _prioritize_statements(ranked, original, limit)


def _prioritize_statements(ranked, original, limit):
    quantitative = {
        "income",
        "ebitda",
        "ebit",
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
        "roa",
        "roe",
        "capital",
        "expenditures",
        "tax",
        "taxes",
        "balance",
        "earnings",
        "working",
        "gross",
    }
    if quantitative.intersection(original):
        # Caption lines distinguish actual financial tables from audit letters and prose references.
        # Many SEC pages carry a "Table of Contents" navigation header, including the tables themselves.
        patterns = (
            r"(?m)^\s*(?:(?:consolidated|combined)\s+)?(?:statements?\s+of\s+(?:(?:consolidated|combined)\s+)?(?:income|operations|earnings)|income\s+statements?)",
            r"(?m)^\s*(?:(?:consolidated|combined)\s+)?(?:statements?\s+of\s+(?:(?:consolidated|combined)\s+)?cash\s+flows?|cash\s+flows?\s+statements?)",
            r"(?m)^\s*(?:(?:consolidated|combined)\s+)?(?:balance\s+sheets?|statements?\s+of\s+financial\s+position)",
        )
        statements = []
        statement_ids = set()
        for pattern in patterns:
            for pair in ranked:
                hit, counts = pair
                body = hit.text.partition("\n")[2]
                heading = re.sub(r"(?im)^\s*table of contents\s*$", "", body[:800]).strip().lower()
                if (
                    re.search(pattern, heading[:400])
                    and sum(count for term, count in counts.items() if term.isdigit()) >= 20
                    and hit.entry_id not in statement_ids
                ):
                    statements.append(pair)
                    statement_ids.add(hit.entry_id)
        reserve = min(len(statements), max(1, limit // 3))
        # Ensure that reserved pages survive deduplication while still filling the remaining positions.
        ranked = statements[:reserve] + ranked
    return ranked


def _score_page(pair, weights, df, average, total, original, query_compact):
    hit, counts = pair
    size = sum(counts.values())
    value = 0.0
    for term, weight in weights.items():
        frequency = counts[term]
        if frequency:
            idf = math.log(1 + (total - df[term] + 0.5) / (df[term] + 0.5))
            value += weight * idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * size / average))
    document_id, _, body = hit.text.partition("\n")
    company = re.split(r"[_\d]", document_id.lower())[0]
    if len(company) >= 3 and re.sub(r"[^a-z0-9]", "", company) in query_compact:
        value *= 2
    heading = re.sub(r"(?im)^\s*table of contents\s*$", "", body[:800]).strip().lower()
    if ("legal" in original or "litigation" in original) and re.search(r"legal\s+proceedings", heading):
        value *= 3
    if any(word in original for word in ("geographies", "geographic", "geography", "operates")) and re.search(
        r"(?:our|business|reportable|operating)\s+(?:divisions|segments|operations)|item\s+1[. ]+business", heading
    ):
        value *= 2
    return value
