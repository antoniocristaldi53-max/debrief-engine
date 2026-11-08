"""Recupero da PubMed via E-utilities NCBI (esearch + efetch).

Niente limite di 20 operatori: la query viaggia in POST. Il DOI si prende solo da
PubmedData/ArticleIdList (con ripiego su ELocationID), mai da .//ArticleId, che pesca
nelle ReferenceList (errore del 05/10/2026).
"""
from __future__ import annotations

import datetime as dt
import os
import time
import urllib.parse
import urllib.request
import json
from lxml import etree

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "debrief-engine"


def _post(endpoint: str, params: dict, retries: int = 5) -> bytes:
    params = dict(params, tool=TOOL)
    key = os.environ.get("NCBI_API_KEY")
    if key:
        params["api_key"] = key
    data = urllib.parse.urlencode(params).encode()
    delay = 1.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{EUTILS}/{endpoint}", data=data)
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            if b"API rate limit exceeded" in body:
                raise RuntimeError("rate limit")
            time.sleep(0.12 if key else 0.35)
            return body
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def journal_query(journals: list[str]) -> str:
    return " OR ".join(f'"{j}"[Journal]' for j in journals)


def esearch(term: str, d_from: dt.date, d_to: dt.date) -> list[str]:
    """Tutti i PMID con EDAT nella finestra (estremi inclusi)."""
    ids: list[str] = []
    retstart = 0
    while True:
        body = _post("esearch.fcgi", {
            "db": "pubmed", "term": term, "datetype": "edat",
            "mindate": d_from.strftime("%Y/%m/%d"), "maxdate": d_to.strftime("%Y/%m/%d"),
            "retmax": 5000, "retstart": retstart, "retmode": "json",
        })
        res = json.loads(body)["esearchresult"]
        ids += res.get("idlist", [])
        count = int(res.get("count", 0))
        retstart += 5000
        if retstart >= count:
            return ids


def count(term: str, d_from: dt.date | None = None, d_to: dt.date | None = None) -> int:
    p = {"db": "pubmed", "term": term, "retmax": 0, "retmode": "json"}
    if d_from:
        p.update(datetype="edat", mindate=d_from.strftime("%Y/%m/%d"),
                 maxdate=d_to.strftime("%Y/%m/%d"))
    return int(json.loads(_post("esearch.fcgi", p))["esearchresult"]["count"])


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def parse_article(art) -> dict:
    mc = art.find("MedlineCitation")
    a = mc.find("Article")
    pmid = mc.findtext("PMID")
    # DOI: solo dall'ArticleIdList di primo livello
    doi = ""
    for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi":
            doi = (aid.text or "").strip()
            break
    if not doi:
        for el in a.findall("ELocationID"):
            if el.get("EIdType") == "doi":
                doi = (el.text or "").strip()
                break
    parts = []
    for t in a.findall("Abstract/AbstractText"):
        label = t.get("Label")
        txt = _text(t)
        parts.append(f"{label}: {txt}" if label else txt)
    abstract = "\n".join(p for p in parts if p).strip()
    edat = None
    for d in art.findall("PubmedData/History/PubMedPubDate"):
        if d.get("PubStatus") == "entrez":
            edat = dt.datetime(int(d.findtext("Year")), int(d.findtext("Month")),
                               int(d.findtext("Day")), int(d.findtext("Hour") or 0),
                               int(d.findtext("Minute") or 0))
    storia = [d.get("PubStatus") for d in art.findall("PubmedData/History/PubMedPubDate")]
    return {
        "pmid": pmid,
        "revisione_paritaria": "received" in storia or "accepted" in storia,
        "doi": doi,
        "titolo_en": _text(a.find("ArticleTitle")),
        "abstract": abstract,
        "rivista_sigla": mc.findtext("MedlineJournalInfo/MedlineTA") or "",
        "rivista": _text(a.find("Journal/Title")),
        "tipi": [_text(p) for p in a.findall("PublicationTypeList/PublicationType")],
        "edat": edat.isoformat() if edat else None,
        "autori": [
            (au.findtext("LastName") or au.findtext("CollectiveName") or "")
            for au in a.findall("AuthorList/Author")
        ][:3],
    }


def efetch(pmids: list[str], chunk: int = 200) -> list[dict]:
    out = []
    for i in range(0, len(pmids), chunk):
        body = _post("efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids[i:i + chunk]),
                                     "retmode": "xml"})
        root = etree.fromstring(body)
        out += [parse_article(x) for x in root.findall("PubmedArticle")]
    return out
