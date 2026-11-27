# debrief-engine

Motore deterministico del **Debrief chirurgico** di Antonio Cristaldi
(artefatto claude.ai «Debrief Chirurgico», scheduled task delle 9:30).

Il codice fa la parte meccanica che prima stava dentro il prompt del task:

| Passo | Modulo | Cosa fa |
|---|---|---|
| Recupero | `debrief/fetch.py` | E-utilities NCBI, query A + B + C su 14 giorni, supplementare 15-28 giorni solo se serve. DOI solo da `PubmedData/ArticleIdList` |
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
python -m debrief.pipeline --seen-dir <cartella out_dir di ArtifactData> --out candidati.json
python -m debrief.pipeline --seen pmid_gia_usciti.txt --out candidati.json   # in alternativa
python -m debrief.pipeline --date 2026-10-14 --now 2026-10-14T09:45 --seen ... --out ...   # backtest
python -m pytest -q
```

`--seen-dir`: la cartella in cui ArtifactData salva i documenti delle edizioni degli ultimi 29 giorni;
il motore legge tutti gli `articoli[].pmid`. `--seen`: in alternativa, un PMID per riga.

## Cambiare una regola

Tutte le regole stanno in `config.yaml`: riviste e tier, termini e pesi per area, scalini, emivite,
scarti. Si cambia una riga, si fanno girare i test, si fa il commit con il motivo.
Ogni errore già visto in produzione ha un test in `tests/test_rules.py`.

## Backtest (08/11/2026)

`backtest/run_backtest.py` confronta il codice con le edizioni pubblicate del 13 e 14 ottobre 2026,
aree a 72h (hpb, colon-retto, eso-gastrico): **32 dei 35 articoli pubblicati** stanno nella top-7 del codice,
2 fra le riserve, 1 escluso correttamente (senza abstract, regola introdotta dopo).
Differenza mediana di score rispetto al task: 1,2 punti.

## Allargamento del recupero (16/11/2026)

Dal 09/11 parete e proctologia uscivano vuote anche a 28 giorni e colon-retto, eso-gastrico e HPB
arrivavano al tetto dei 14 giorni con 0-2 articoli: con un'edizione al giorno, il pool delle 35 riviste
veniva consumato più in fretta di quanto si riempisse (circa 3,5-4 lavori nuovi al giorno per le aree
ad alto volume, 1,4 per la parete, 0,7 per la proctologia).

- Query **C** con 12 riviste chirurgiche (sigla MedlineTA e prefisso DOI verificati): J Hepatobiliary
  Pancreat Sci e Surg Obes Relat Dis tier 2, le altre tier 3. Aggiunte anche alle supplementari
  di parete e proctologia.
- `Ann Surg Treat Res` da tier 1 a tier 3 (errore di tier).
- `thymic`, `thymoma`, `intrathoracic` fra le esclusioni del colon-retto (HITHOC agganciava
  `cytoreductive`).
- `--seen-dir`: il motore legge i PMID già usciti direttamente dai JSON delle edizioni.

Prova sullo stato del 16/11 sera (stesse edizioni già uscite): parete da 0 a 3 articoli a 7 giorni,
proctologia da 0 a 2 a 28 giorni, HPB da 2 a 14 giorni a 3 a 72 ore; colon-retto ed eso-gastrico
invariati o +1. La proctologia resta strutturalmente scarsa (in tutto MEDLINE meno di 2 lavori al giorno):
edizioni corte o vuote in quell'area sono attese. `Int J Surg` non ha nuovi record in PubMed dal
29/09/2026: è un ritardo di deposito dell'editore, non della sigla.

## Penalità per tipo di testo e carcinosi non colorettale (18/11/2026)

Nell'edizione del 18/11 lo score metteva in top-7 un case report (chilo-peritoneo dopo resezione
anteriore ultrabassa, 57,0) e una revisione narrativa (lesioni serrate, 60,7) sopra studi clinici
comparativi, e assegnava al colon-retto «PERISCOPE II: lessons learned» (cancro gastrico) per i soli
termini peritoneali.

- `formula.penalita_segnali`: score × 0,75 per `case_report`, × 0,85 per `revisione_narrativa`
  (si applica la più severa). Il campo `penalita_tipo` di ogni candidato riporta il fattore usato.
- `case_report` riconosciuto anche dall'inizio dell'abstract («A 55 year old woman…», «We present a
  case…»); «a case-control/series» non è più un case report.
- `revisione_narrativa`: PublicationType Review senza segni di revisione sistematica/meta-analisi
  nel testo e senza abstract strutturato (METHODS/RESULTS). Molte meta-analisi e alcune coorti sono
  indicizzate solo come Review: restano senza penalità.
- `aree.colon-retto.termini_peritoneali`: HIPEC, cytoreductive, peritoneal metastases e peritonectomy
  contano per il colon-retto solo con un'ancora colorettale o appendicolare (`ancore_colorettali`).

Prova sul recupero del 18/11 (729 record): PERISCOPE II passa a eso-gastrico; escono dal colon-retto
anche una serie PIPAC sul mesotelioma e un consenso PSOGI generico senza riferimenti colorettali
(restano senza area). In top-7 colon-retto il case report e la revisione narrativa escono e
entrano LASRE e la stadiazione Medicare, le stesse scelte fatte a mano nell'edizione. Fra i record in
area, 6 marcati case report e 10 revisioni narrative; un'analisi bibliometrica resta marcata
narrativa (falso positivo accettato).

## Resoconti di congresso e bacino della proctologia (24/11/2026)

Nell'edizione del 24/11 il resoconto del congresso PSOGI 2025 («Take-home messages from the 2025 15th
PSOGI congress», nessun dato originale) stava al rank 2 del colon-retto con 57,7, e la proctologia
arrivava al tetto dei 28 giorni con un solo articolo (27 in finestra: 17 già usciti, 9 scarti).

- Segnale `sintesi_congresso`: titolo con una parola del congresso (congress, meeting, symposium,
  summit, conference, workshop) **e** una del resoconto (take-home, highlights, key updates/messages,
  proceedings, meeting/conference report, report from, summary of, lessons from). Non si applica se
  il lavoro è già marcato linea guida (le consensus conference restano tali). Penalità × 0,85,
  come le revisioni narrative.
- `J Anus Rectum Colon` (Japan Society of Coloproctology, tier 3, DOI 10.23922) nella query C e nella
  supplementare della proctologia: 7 lavori proctologici in 28 giorni, quanti Dis Colon Rectum.
  Fuori whitelist nessun'altra rivista chirurgica superava un lavoro proctologico in 28 giorni
  (il resto è pediatria, case report e riviste generaliste).
- Grafia britannica fra i termini della proctologia: haemorrhoid, faecal incontinence, fistula in ano
  (1,0), obstructed defaecation (0,9). Colorectal Dis, Tech Coloproctol e BJS la usano.

Prova sul recupero del 24/11 con gli stessi PMID già usciti: il PSOGI scende da 57,7 a 48,9 (rank 4);
la proctologia passa da 1 a 7 articoli (9 selezionabili a 28 giorni), di cui 5 di J Anus Rectum Colon
e 1 recuperato dalla grafia britannica. Gran parte dei lavori JARC viene da un unico fascicolo
indicizzato il 29/10: il guadagno stabile atteso è di circa un lavoro proctologico in più a settimana,
non uno al giorno. La proctologia resta un'area a basso volume.

## Proctologia: due riviste in più (27/11/2026)

La proctologia usciva vuota al tetto dei 28 giorni in quattro edizioni su sette (21-27/11): il pool
delle whitelist produce meno di un lavoro nuovo al giorno. Allungare gli scalini oltre i 28 giorni
non serve: i 13 lavori proctologici fra 29 e 42 giorni erano tutti già pubblicati (10-28/10) e
sarebbero stati ripubblicati, perché i PMID già usciti coprono 29 giorni.

- `J Crohns Colitis` (ECCO, tier 2) e `J Surg Res` (tier 3) nella query C e nella supplementare
  della proctologia, con prefissi DOI verificati.
- Prova sull'edizione del 27/11: proctologia da 0 articoli a 28 giorni a 3 articoli a 14 giorni.
