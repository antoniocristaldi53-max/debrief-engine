"""Backtest: pipeline vs edizioni pubblicate, solo aree a 72h (il seen-set dei 3 giorni prima è completo)."""
import json, datetime as dt, sys
sys.path.insert(0, "..")
from debrief import pipeline
from zoneinfo import ZoneInfo
pub = json.load(open("pubblicati.json"))
cfg = pipeline.load_cfg()
casi = {"2026-10-13": "11:39", "2026-10-14": "09:45"}
report = {}
for d, ora in casi.items():
    seen = {p for dd, aree in pub.items() if dd < d for l in aree.values() for p in l}
    now = dt.datetime.fromisoformat(f"{d}T{ora}").replace(tzinfo=ZoneInfo("Europe/Rome"))
    res = pipeline.run(dt.date.fromisoformat(d), now, seen, cfg)
    json.dump(res, open(f"candidati_{d}.json", "w"), ensure_ascii=False, indent=1)
    for area in ["hpb", "colon-retto", "eso-gastrico"]:
        a = res["aree"][area]
        codice = [c["pmid"] for c in a["articoli"]]
        riserve = [c["pmid"] for c in a["riserve"]]
        reale = pub[d][area]
        report[f"{d} {area}"] = {
            "finestra_codice": a["finestra"], "sel_codice": len(codice), "sel_reale": len(reale),
            "in_comune_top7": len(set(codice) & set(reale)),
            "reali_tra_le_riserve": len(set(riserve) & set(reale)),
            "reali_mancanti": sorted(set(reale) - set(codice) - set(riserve)),
            "codice_non_pubblicati": [ (c["pmid"], c["score"], c["titolo_en"][:70]) for c in a["articoli"] if c["pmid"] not in reale],
        }
json.dump(report, open("report.json", "w"), ensure_ascii=False, indent=1)
for k, v in report.items():
    print(k, v["finestra_codice"], f'top7 comune {v["in_comune_top7"]}/{v["sel_reale"]}', f'+riserve {v["reali_tra_le_riserve"]}', 'mancanti', v["reali_mancanti"])
