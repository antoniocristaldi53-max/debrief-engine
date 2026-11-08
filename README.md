# debrief-engine

Motore deterministico del **Debrief chirurgico** di Antonio Cristaldi
(artefatto claude.ai «Debrief Chirurgico», scheduled task delle 9:30).

Il codice fa la parte meccanica che prima stava dentro il prompt del task:

| Passo | Modulo | Cosa fa |
|---|---|---|
| Recupero | `debrief/fetch.py` | E-utilities NCBI, query A + B su 14 giorni, supplementare 15-28 giorni solo se serve. DOI solo da `PubmedData/ArticleIdList` |
| Scarti obbligatori | `debrief/rules.py` → `scarto()` | errata, lettere, commenti, visual abstract, editoriali senza abstract, abstract vuoto |
| Aree e confini | `rules.classifica()` | una sola area per PMID; confine HPB/colon-retto, proctologia ≥ 1,8, ovaio fuori dal colon-retto |
| Deduplica | `pipeline.run()` | scarta i PMID già pubblicati **prima** del ranking |
| Scalini | `pipeline.run()` | 72h→7→10→14 (alto volume), 7→10→14→21→28 (basso volume), stop al primo con ≥ 3 |
| Punteggio | `rules.punteggio()` | `(0,35×rivista + 0,45×keyword + 0,20×recency)×100`, emivita per scalino, peso 1,2 linee guida, penalità 0,70 |

Il modello (scheduled task) riceve `candidati.json` e fa solo la parte editoriale:
titoli in italiano, take-home, rilevanza, riordino editoriale motivato, trial, contesto, scrittura nel database.

## Uso

```bash
pip install -r requirements.txt --break-system-packages
python -m debrief.pipeline --seen pmid_gia_usciti.txt --out candidati.json
python -m debrief.pipeline --date 2026-10-14 --now 2026-10-14T09:45 --seen ... --out ...   # backtest
python -m pytest -q
```

`--seen`: un PMID per riga (le edizioni degli ultimi 29 giorni, lette dal database dell'artefatto).

## Cambiare una regola

Tutte le regole stanno in `config.yaml`: riviste e tier, termini e pesi per area, scalini, emivite,
scarti. Si cambia una riga, si fanno girare i test, si fa il commit con il motivo.
Ogni errore già visto in produzione ha un test in `tests/test_rules.py`.

## Backtest (08/11/2026)

`backtest/run_backtest.py` confronta il codice con le edizioni pubblicate del 13 e 14 ottobre 2026,
aree a 72h (hpb, colon-retto, eso-gastrico): **32 dei 35 articoli pubblicati** stanno nella top-7 del codice,
2 fra le riserve, 1 escluso correttamente (senza abstract, regola introdotta dopo).
Differenza mediana di score rispetto al task: 1,2 punti.
