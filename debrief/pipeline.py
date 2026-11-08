"""Pipeline: recupero -> scarti -> assegnazione area -> deduplica -> scalini -> punteggio.

Uso:
  python -m debrief.pipeline --seen pmid_gia_usciti.txt --out candidati.json
  python -m debrief.pipeline --date 2026-11-02 --now 2026-11-02T09:30 ...   (backtest)

Il modello (scheduled task) riceve candidati.json e fa solo la parte editoriale:
titoli in italiano, take-home, rilevanza, trial, contesto, scrittura nel database.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from zoneinfo import ZoneInfo

import yaml

from . import fetch, rules

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROMA = ZoneInfo("Europe/Rome")
ESPRESSIONI = {3: "nelle ultime 72 ore", 7: "nell'ultima settimana", 10: "negli ultimi 10 giorni",
               14: "nelle ultime due settimane", 21: "nelle ultime tre settimane",
               28: "nell'ultimo mese"}


def load_cfg(path: pathlib.Path | None = None) -> dict:
    with open(path or ROOT / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    # chiavi numeriche dei pesi come float
    for a in cfg["aree"].values():
        a["termini"] = {float(k): v for k, v in a["termini"].items()}
    cfg["emivita_ore"] = {int(k): v for k, v in cfg["emivita_ore"].items()}
    return cfg


def etichetta_scalino(n: int) -> str:
    return "72h" if n == 3 else f"{n} giorni"


def finestra(date: dt.date, n: int, iniziale: int) -> str:
    da = date - dt.timedelta(days=n - 1)
    s = f"EDAT {da:%Y/%m/%d} → {date:%Y/%m/%d} ({etichetta_scalino(n)}"
    if n != iniziale:
        s += f", allargata da {etichetta_scalino(iniziale)}"
    return s + ")"


def recupera(journals_sets: list[list[str]], d_from: dt.date, d_to: dt.date,
             log: dict, chiave: str) -> list[dict]:
    pmids: set[str] = set()
    for js in journals_sets:
        ids = fetch.esearch(fetch.journal_query(js), d_from, d_to)
        log.setdefault(chiave, []).append(len(ids))
        pmids |= set(ids)
    recs = fetch.efetch(sorted(pmids))
    log[f"{chiave}_unione"] = len(pmids)
    log[f"{chiave}_metadati"] = len(recs)
    return recs


def verifica_sigle(cfg: dict, d_from: dt.date, d_to: dt.date, unione: int) -> dict:
    """La somma dei conteggi per rivista deve coincidere con l'unione (riviste disgiunte)."""
    js = cfg["query"]["A"] + cfg["query"]["B"]
    per = {j: fetch.count(f'"{j}"[Journal]', d_from, d_to) for j in js}
    zero = [j for j, c in per.items() if c == 0]
    non_risolte = [j for j in zero if fetch.count(f'"{j}"[Journal]') < 100]
    return {"somma_per_rivista": sum(per.values()), "unione": unione,
            "coincide": sum(per.values()) == unione, "riviste_a_zero": zero,
            "sigle_sospette": non_risolte}


def prepara(recs: list[dict], cfg: dict, now_naive: dt.datetime) -> list[dict]:
    out = []
    for r in recs:
        if r["edat"] and dt.datetime.fromisoformat(r["edat"]) > now_naive:
            continue  # backtest: non ancora indicizzato all'ora di esecuzione
        r["scarto"] = rules.scarto(r, cfg)
        r.update(rules.classifica(r, cfg))
        r["segnali"] = rules.segnali(r, cfg)
        r["doi_plausibile"] = rules.doi_plausibile(r)
        out.append(r)
    return out


def run(date: dt.date, now: dt.datetime, seen: set[str], cfg: dict,
        verifica: bool = False) -> dict:
    now_naive = now.astimezone(ROMA).replace(tzinfo=None)
    log: dict = {}
    base_from = date - dt.timedelta(days=13)
    recs = prepara(recupera([cfg["query"]["A"], cfg["query"]["B"]], base_from, date, log, "base"),
                   cfg, now_naive)
    if verifica:
        log["verifica_sigle"] = verifica_sigle(cfg, base_from, date, log["base_unione"])
    by_pmid = {r["pmid"]: r for r in recs}
    usati: set[str] = set()
    aree_out = {}
    f = cfg["formula"]
    for key, area in cfg["aree"].items():
        scalini = area["scalini"]
        supplementare_fatto = False
        tentativi = []
        for n in scalini:
            if n > 14 and not supplementare_fatto:
                extra = recupera([cfg["query"]["supplementare"][key]],
                                 date - dt.timedelta(days=27), date - dt.timedelta(days=14),
                                 log, f"supplementare_{key}")
                for r in prepara(extra, cfg, now_naive):
                    by_pmid.setdefault(r["pmid"], r)
                supplementare_fatto = True
            da = date - dt.timedelta(days=n - 1)
            in_fin = [r for r in by_pmid.values() if r["area"] == key and r["edat"]
                      and dt.date.fromisoformat(r["edat"][:10]) >= da]
            scartati = [r for r in in_fin if r["scarto"]]
            dedup = [r for r in in_fin if not r["scarto"] and r["pmid"] in seen]
            validi = [r for r in in_fin if not r["scarto"] and r["pmid"] not in seen
                      and r["pmid"] not in usati]
            tentativi.append({"scalino": n, "in_finestra": len(in_fin),
                              "scarti_obbligatori": len(scartati), "gia_usciti": len(dedup),
                              "selezionabili": len(validi)})
            if len(validi) >= f["minimo_area"]:
                break
        cand = []
        for r in validi:
            kw = r["punteggi_aree"][key]
            p = rules.punteggio(r, kw, n, now_naive, cfg)
            cand.append({**{k: r[k] for k in ("pmid", "doi", "titolo_en", "abstract", "rivista",
                                              "rivista_sigla", "tipi", "edat", "autori",
                                              "segnali", "doi_plausibile", "aree_secondarie")},
                         "termini": r["termini"], "keyword": kw, **p})
        cand.sort(key=lambda c: (-c["score"], c["pmid"]))
        top = cand[: f["top_n"]]
        for i, c in enumerate(top, 1):
            c["rank"] = i
            usati.add(c["pmid"])
        extra = cand[f["top_n"]: f["top_n"] + f["candidati_extra"]]
        oltre14 = [c["pmid"] for c in top if c["edat"] and
                   (date - dt.date.fromisoformat(c["edat"][:10])).days >= 14]
        aree_out[key] = {
            "area": key, "areaLabel": area["label"], "scalino_giorni": n,
            "scalino_iniziale": scalini[0],
            "finestra": finestra(date, n, scalini[0]),
            "espressione_sintesi": ESPRESSIONI[n],
            "tetto_raggiunto": n == scalini[-1],
            "valutati": len(validi), "selezionati": len(top),
            "tentativi_scalini": tentativi,
            "pmid_oltre_14_giorni": oltre14,
            "articoli": top, "riserve": extra,
        }
    scarti_tot = sum(1 for r in by_pmid.values() if r["scarto"])
    dedup_tot = sum(1 for r in by_pmid.values() if r["pmid"] in seen and not r["scarto"]
                    and r["area"])
    return {
        "data_edizione": date.isoformat(), "generato": now.isoformat(),
        "recupero": log, "record_totali": len(by_pmid), "scarti_obbligatori": scarti_tot,
        "scartati_deduplica": dedup_tot, "pmid_gia_usciti_in_input": len(seen),
        "aree": aree_out,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="data edizione AAAA-MM-GG (default: oggi a Roma)")
    ap.add_argument("--now", help="ISO, ora di Roma (default: adesso)")
    ap.add_argument("--seen", help="file con i PMID già pubblicati, uno per riga")
    ap.add_argument("--out", default="candidati.json")
    ap.add_argument("--verifica-sigle", action="store_true")
    a = ap.parse_args(argv)
    now = dt.datetime.fromisoformat(a.now).replace(tzinfo=ROMA) if a.now \
        else dt.datetime.now(ROMA)
    date = dt.date.fromisoformat(a.date) if a.date else now.date()
    seen = set()
    if a.seen:
        seen = {l.strip() for l in open(a.seen) if l.strip()}
    res = run(date, now, seen, load_cfg(), a.verifica_sigle)
    pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    for k, v in res["aree"].items():
        print(f'{k:13s} {v["finestra"]:55s} sel {v["selezionati"]}  valutati {v["valutati"]}')
    print(f'record {res["record_totali"]}  scarti {res["scarti_obbligatori"]}  '
          f'dedup {res["scartati_deduplica"]}', file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
