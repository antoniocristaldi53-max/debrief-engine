"""Regole deterministiche: scarti obbligatori, assegnazione all'area, punteggio."""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache

# Prefissi DOI plausibili per rivista (controllo del PASSO 3)
DOI_PREFISSI = {
    "Ann Surg": ["10.1097"], "JAMA Surg": ["10.1001"], "Br J Surg": ["10.1093", "10.1002"],
    "Ann Surg Oncol": ["10.1245"], "Surgery": ["10.1016"], "N Engl J Med": ["10.1056"],
    "Lancet": ["10.1016"], "Lancet Oncol": ["10.1016"], "Lancet Gastroenterol Hepatol": ["10.1016"],
    "J Hepatol": ["10.1016"], "Gastroenterology": ["10.1053"], "Gut": ["10.1136"],
    "HPB (Oxford)": ["10.1016"], "Hernia": ["10.1007"], "Ann Surg Treat Res": ["10.4174"],
    "Dis Colon Rectum": ["10.1097"], "Gastric Cancer": ["10.1007"], "Surg Endosc": ["10.1007"],
    "World J Surg": ["10.1002", "10.1007"], "J Gastrointest Surg": ["10.1016", "10.1007"],
    "Int J Surg": ["10.1097", "10.1016"], "Am J Surg": ["10.1016"], "Eur J Surg Oncol": ["10.1016"],
    "Pancreatology": ["10.1016"], "Liver Int": ["10.1111"], "Surg Oncol": ["10.1016"],
    "J Am Coll Surg": ["10.1097"], "Colorectal Dis": ["10.1111"], "Dis Esophagus": ["10.1093"],
    "Obes Surg": ["10.1007"], "Tech Coloproctol": ["10.1007"], "J Surg Oncol": ["10.1002"],
    "Updates Surg": ["10.1007"], "Langenbecks Arch Surg": ["10.1007"], "BJS Open": ["10.1093"],
    "Int J Colorectal Dis": ["10.1007"], "Surg Innov": ["10.1177"],
    # 16/11/2026, prefissi verificati su E-utilities
    "J Hepatobiliary Pancreat Sci": ["10.1002"], "Surg Obes Relat Dis": ["10.1016"],
    "J Abdom Wall Surg": ["10.3389"], "Ann Coloproctol": ["10.3393"],
    "Ann Gastroenterol Surg": ["10.1002"], "BMC Surg": ["10.1186"], "Am Surg": ["10.1177"],
    "ANZ J Surg": ["10.1111"], "Ann R Coll Surg Engl": ["10.1308"], "Can J Surg": ["10.1503"],
    "J Robot Surg": ["10.1007"], "J Laparoendosc Adv Surg Tech A": ["10.1089", "10.1177"],
    # 24/11/2026
    "J Anus Rectum Colon": ["10.23922"],
    # 27/11/2026, prefissi verificati su E-utilities
    "J Crohns Colitis": ["10.1093"], "J Surg Res": ["10.1016"],
}

LINEA_GUIDA_TITOLO = re.compile(
    r"\b(guidelines?|consensus statement|consensus conference|delphi consensus|"
    r"position statement|recommendations)\b", re.I)
LINEA_GUIDA_NO = re.compile(r"\b(adherence|compliance|concordance|implementation of)\b", re.I)


@lru_cache(maxsize=None)
def anchor_regex(term: str) -> re.Pattern:
    """Ancora come inizio di parola: 'liver' non deve agganciare 'delivery'."""
    return re.compile(rf"(?<![A-Za-z]){re.escape(term)}", re.I)


@lru_cache(maxsize=None)
def term_regex(term: str, max_len: int) -> re.Pattern:
    esc = re.escape(term)
    if len(term) <= max_len:
        return re.compile(rf"(?<![A-Za-z0-9]){esc}(?![A-Za-z0-9])", re.I)
    # Termini lunghi: inizio di parola obbligatorio, desinenze libere (plurali).
    # Senza questo 'rectal cancer' viene contato dentro 'colorectal cancer'.
    return re.compile(rf"(?<![A-Za-z0-9]){esc}", re.I)


def area_keyword(text: str, termini: dict, max_len: int) -> tuple[float, list[str]]:
    tot, hit = 0.0, []
    for peso, lista in termini.items():
        for t in lista:
            if term_regex(t, max_len).search(text):
                tot += float(peso)
                hit.append(t)
    return round(tot, 3), hit


def scarto(rec: dict, cfg: dict) -> str | None:
    """Motivo dello scarto obbligatorio, oppure None."""
    s = cfg["scarti"]
    tipi = set(rec["tipi"])
    for t in s["tipi_pubblicazione"]:
        if t in tipi:
            return f"tipo: {t}"
    titolo = rec["titolo_en"].lower()
    for pat in s["titolo"]:
        if re.search(pat, titolo):
            return f"titolo: {pat}"
    if s["editoriale"] in tipi and len(rec["abstract"]) < s["editoriale_abstract_min"]:
        return "editoriale senza abstract strutturato"
    if not rec["abstract"].strip():
        # Regola del 25/10/2026: scarto. Ma un record con date di revisione paritaria è quasi
        # sempre un articolo originale il cui abstract l'editore non ha ancora depositato:
        # lo si conta a parte, perché potrebbe rientrare nei giorni successivi.
        if rec.get("revisione_paritaria"):
            return "abstract non ancora depositato"
        return "abstract vuoto"
    return None


def classifica(rec: dict, cfg: dict) -> dict:
    """Punteggi keyword per area e area assegnata (una sola: nessun PMID in due aree)."""
    ml = cfg["formula"]["boundary_max_len"]
    text = f'{rec["titolo_en"]} {rec["abstract"]}'
    punteggi, hits = {}, {}
    for key, area in cfg["aree"].items():
        punteggi[key], hits[key] = area_keyword(text, area["termini"], ml)
    # Confine HPB: termine colorettale senza ancora HPB -> fuori dall'HPB
    ancore = cfg["aree"]["hpb"]["ancore"]
    if punteggi["colon-retto"] > 0 and not any(
            anchor_regex(a).search(text) for a in ancore):
        punteggi["hpb"] = 0.0
    # Pertinenza colon-retto: oncologia ginecologica fuori
    cr = cfg["aree"]["colon-retto"]
    escl = cr.get("esclusioni_pertinenza", [])
    if any(anchor_regex(e).search(text) for e in escl) and punteggi["colon-retto"] > 0:
        punteggi["colon-retto"] = 0.0
    # Termini peritoneali senza ancora colorettale: carcinosi di altra origine (gastrica...)
    perit = set(cr.get("termini_peritoneali", []))
    if perit & set(hits["colon-retto"]) and not any(
            anchor_regex(a).search(text) for a in cr.get("ancore_colorettali", [])):
        pesi = {t: p for p, lista in cr["termini"].items() for t in lista}
        tolti = [t for t in hits["colon-retto"] if t in perit]
        punteggi["colon-retto"] = round(max(0.0, punteggi["colon-retto"]
                                            - sum(pesi[t] for t in tolti)), 3)
        hits["colon-retto"] = [t for t in hits["colon-retto"] if t not in perit]
    # 19/11/2026: termini eso-gastrici deboli senza ancora esofago-gastrica (invasione duodenale
    # di un tumore biliare, varici da ipertensione portale): non agganciano l'eso-gastrico
    eg = cfg["aree"]["eso-gastrico"]
    deboli = set(eg.get("termini_deboli", []))
    if deboli & set(hits["eso-gastrico"]) and not any(
            anchor_regex(a).search(text) for a in eg.get("ancore_esogastriche", [])):
        pesi = {t: p for p, lista in eg["termini"].items() for t in lista}
        tolti = [t for t in hits["eso-gastrico"] if t in deboli]
        punteggi["eso-gastrico"] = round(max(0.0, punteggi["eso-gastrico"]
                                             - sum(pesi[t] for t in tolti)), 3)
        hits["eso-gastrico"] = [t for t in hits["eso-gastrico"] if t not in deboli]
    soglia = cfg["aree"]["proctologia"]["soglia_prevalenza"]
    if punteggi["proctologia"] >= soglia:
        area = "proctologia"
    else:
        positive = {k: v for k, v in punteggi.items() if v > 0}
        area = max(positive, key=positive.get) if positive else None
    secondarie = [k for k, v in punteggi.items() if v > 0 and k != area]
    return {"area": area, "punteggi_aree": punteggi, "termini": hits.get(area, []),
            "aree_secondarie": secondarie}


def segnali(rec: dict, cfg: dict) -> list[str]:
    out = sorted({v for k, v in cfg["scarti"]["segnali_editoriali"].items() if k in rec["tipi"]})
    if "linea_guida" not in out and LINEA_GUIDA_TITOLO.search(rec["titolo_en"]) \
            and not LINEA_GUIDA_NO.search(rec["titolo_en"]):
        out.append("linea_guida_da_titolo")
    if re.search(r"\bvideo\b", rec["titolo_en"], re.I) and "video" not in out:
        out.append("video")
    s = cfg["scarti"]
    if "case_report" not in out and (
            re.search(r"\bcase report\b|\ba case\b(?![- ](control|series|mix))", rec["titolo_en"], re.I)
            or re.search(s["case_report_abstract"], rec["abstract"][:300], re.I)):
        out.append("case_report")
    # 18/11/2026: revisione narrativa = PublicationType Review senza segni di revisione sistematica
    # (molte meta-analisi sono indicizzate solo come Review: si guarda anche il testo)
    if "Review" in rec["tipi"] and not {"metanalisi", "revisione_sistematica"} & set(out) \
            and not re.search(s["revisione_sistematica_testo"],
                              f'{rec["titolo_en"]} {rec["abstract"]}', re.I) \
            and not re.search(s["abstract_strutturato"], rec["abstract"]):
        out.append("revisione_narrativa")
    # 24/11/2026: resoconto di congresso (sintesi senza dati originali)
    if not {"linea_guida", "linea_guida_da_titolo"} & set(out) \
            and re.search(s["congresso_titolo"], rec["titolo_en"], re.I) \
            and re.search(s["resoconto_titolo"], rec["titolo_en"], re.I):
        out.append("sintesi_congresso")
    return sorted(out)


def doi_plausibile(rec: dict) -> bool:
    pref = DOI_PREFISSI.get(rec["rivista_sigla"])
    if not rec["doi"]:
        return False
    return pref is None or any(rec["doi"].startswith(p) for p in pref)


def punteggio(rec: dict, kw: float, giorni_scalino: int, now: dt.datetime, cfg: dict) -> dict:
    f = cfg["formula"]
    tier = cfg["riviste"].get(rec["rivista_sigla"])
    if tier is None:
        return {"score": 0.0, "fuori_whitelist": True}
    sg = rec.get("segnali", [])
    peso = f["peso_linee_guida"] if ("linea_guida" in sg or "linea_guida_da_titolo" in sg) \
        else cfg["tier_peso"][tier]
    c_riv = peso / f["peso_linee_guida"]
    c_kw = min(kw, f["keyword_cap"]) / f["keyword_cap"]
    if rec["edat"]:
        ore = max(0.0, (now - dt.datetime.fromisoformat(rec["edat"])).total_seconds() / 3600)
        c_rec = 0.5 ** (ore / cfg["emivita_ore"][giorni_scalino])
    else:
        ore, c_rec = None, f["recency_data_mancante"]
    s = (f["w_rivista"] * c_riv + f["w_keyword"] * c_kw + f["w_recency"] * c_rec) * 100
    breve = len(rec["abstract"].strip()) < f["abstract_breve_caratteri"]
    if breve:
        s *= f["penalita_abstract_breve"]
    # 18/11/2026: penalità per tipo di testo (la più severa se più segnali)
    pen_tipo = min([f.get("penalita_segnali", {}).get(x, 1.0) for x in sg] or [1.0])
    s *= pen_tipo
    return {"score": round(s, 1), "tier": tier, "c_rivista": round(c_riv, 3),
            "c_keyword": round(c_kw, 3), "c_recency": round(c_rec, 3),
            "ore_eta": round(ore, 1) if ore is not None else None,
            "penalita_abstract": breve, "penalita_tipo": pen_tipo}
