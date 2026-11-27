"""Test sui casi reali che il prompt del task documenta come errori già commessi."""
import datetime as dt

import pytest
from lxml import etree

from debrief import fetch, pipeline, rules

CFG = pipeline.load_cfg()
NOW = dt.datetime(2026, 10, 22, 9, 30)


def rec(titolo, abstract="Background: x. Methods: y. Results: z. " * 3, rivista="Ann Surg",
        tipi=("Journal Article",), edat="2026-10-21T10:00:00", **kw):
    r = {"pmid": kw.get("pmid", "1"), "doi": kw.get("doi", "10.1097/SLA.1"),
         "titolo_en": titolo, "abstract": abstract, "rivista_sigla": rivista, "rivista": rivista,
         "tipi": list(tipi), "edat": edat, "autori": [], "revisione_paritaria": True}
    r["segnali"] = rules.segnali(r, CFG)
    return r


def score(r, area, giorni=3):
    cl = rules.classifica(r, CFG)
    return rules.punteggio(r, cl["punteggi_aree"][area], giorni, NOW, CFG)["score"], cl


# --- formula: i due correttivi documentati per le linee guida -------------------------------
def test_peso_linee_guida_vale_14_6_punti():
    r = rec("EAES-SAGES guideline update on diverticular disease", rivista="Surg Endosc",
            tipi=("Journal Article", "Practice Guideline"))
    con = rules.punteggio(r, 2.0, 7, NOW, CFG)["score"]
    r["segnali"] = []
    senza = rules.punteggio(r, 2.0, 7, NOW, CFG)["score"]
    # 0,35 x (1 - 0,7/1,2) x 100 = 14,58: è la differenza 45,6 -> 60,2 del 22/10/2026
    assert con - senza == pytest.approx(14.6, abs=0.1)


def test_linea_guida_riconosciuta_dal_titolo_ma_non_l_aderenza():
    assert "linea_guida_da_titolo" in rec("SAGES consensus statement on gastroparesis")["segnali"]
    assert "linea_guida_da_titolo" not in rec("Adherence to guidelines in rectal cancer")["segnali"]


# --- dizionari -----------------------------------------------------------------------------
def test_colecistectomia_robotica_non_sottostimata():
    s, cl = score(rec("Robotic cholecystectomy versus laparoscopic cholecystectomy: an RCT"), "hpb")
    assert cl["area"] == "hpb"
    # 0,9 + 0,9 + 0,7 (cholecystectomy isolata) = 2,5, non più il solo 0,7
    assert cl["punteggi_aree"]["hpb"] == pytest.approx(2.5)


def test_termini_brevi_solo_con_confine_di_parola():
    _, cl = score(rec("Step-by-step technique in a series of patients"), "parete")
    assert cl["punteggi_aree"]["parete"] == 0       # 'TEP' non aggancia 'step'
    _, cl = score(rec("eTEP versus TAPP for inguinal hernia"), "parete")
    assert set(cl["termini"]) >= {"eTEP", "TAPP", "inguinal hernia"}
    assert "TEP" not in cl["termini"]               # 'TEP' non aggancia 'eTEP'


def test_ancore_hpb_inizio_parola():
    # 'liver' dentro 'delivery' non è un'ancora: lavoro colorettale puro resta fuori dall'HPB
    _, cl = score(rec("Drug delivery and portal-free colectomy outcomes in rectal cancer",
                      abstract="Colectomy for rectal cancer with delivery of chemotherapy. " * 3),
                  "colon-retto")
    assert cl["punteggi_aree"]["hpb"] == 0
    assert cl["area"] == "colon-retto"


def test_rectal_cancer_non_contato_dentro_colorectal_cancer():
    _, cl = score(rec("Colorectal cancer screening"), "colon-retto")
    assert cl["termini"] == ["colorectal cancer"]


def test_metastasi_epatiche_colorettali_restano_hpb():
    _, cl = score(rec("Hepatectomy for colorectal liver metastases after colorectal cancer"),
                  "hpb")
    assert cl["area"] == "hpb"


def test_confine_proctologia_prevale_a_1_8():
    _, cl = score(rec("Perianal fistula in Crohn disease: seton and LIFT procedure"), "proctologia")
    assert cl["punteggi_aree"]["proctologia"] >= 1.8
    assert cl["area"] == "proctologia"


def test_ovaio_fuori_dal_colon_retto():
    _, cl = score(rec("HIPEC and cytoreductive surgery in advanced ovarian cancer"), "colon-retto")
    assert cl["punteggi_aree"]["colon-retto"] == 0


# --- scarti obbligatori --------------------------------------------------------------------
@pytest.mark.parametrize("titolo,tipi", [
    ("ASO Visual Abstract: Outcomes of hepatectomy", ("Journal Article",)),
    ("ASO Author Reflections: pancreatectomy", ("Journal Article",)),
    ("Invited Commentary: colectomy in the elderly", ("Journal Article",)),
    ("Reply to: hernia repair outcomes", ("Journal Article",)),
    ("Erratum to: gastrectomy trial", ("Published Erratum",)),
    ("Hernia repair outcomes", ("Letter",)),
    ("Thank you to our reviewers", ("Journal Article",)),
])
def test_scarti_obbligatori(titolo, tipi):
    assert rules.scarto(rec(titolo, tipi=tipi), CFG)


def test_abstract_vuoto_scartato_e_distinto():
    r = rec("Completion cholecystectomy is safe", abstract="")
    assert rules.scarto(r, CFG) == "abstract non ancora depositato"
    r["revisione_paritaria"] = False
    assert rules.scarto(r, CFG) == "abstract vuoto"


def test_editoriale_con_abstract_strutturato_ammesso():
    r = rec("Critical appraisal of the trial", tipi=("Editorial",), abstract="M: " + "x" * 500)
    assert rules.scarto(r, CFG) is None


def test_penalita_abstract_breve():
    r = rec("Ventral hernia repair", abstract="Short note.")
    pieno = rules.punteggio(rec("Ventral hernia repair"), 1.0, 7, NOW, CFG)["score"]
    assert rules.punteggio(r, 1.0, 7, NOW, CFG)["score"] == pytest.approx(pieno * 0.7, abs=0.1)


# --- recency e scalini ---------------------------------------------------------------------
def test_emivita_legata_allo_scalino():
    r = rec("x", edat="2026-10-18T09:30:00")         # 96 ore
    assert rules.punteggio(r, 0, 3, NOW, CFG)["c_recency"] == pytest.approx(0.5 ** (96 / 36), abs=1e-3)
    assert rules.punteggio(r, 0, 10, NOW, CFG)["c_recency"] == pytest.approx(0.5, abs=1e-3)


def test_etichette_finestra():
    d = dt.date(2026, 10, 5)
    assert pipeline.finestra(d, 3, 3) == "EDAT 2026/10/03 → 2026/10/05 (72h)"
    assert pipeline.finestra(d, 7, 3) == "EDAT 2026/09/29 → 2026/10/05 (7 giorni, allargata da 72h)"
    assert pipeline.finestra(d, 28, 7) == \
        "EDAT 2026/09/08 → 2026/10/05 (28 giorni, allargata da 7 giorni)"


def test_tutte_le_riviste_delle_query_hanno_un_tier():
    js = [j for q in pipeline.query_base(CFG) for j in q]
    js += [j for q in CFG["query"]["supplementare"].values() for j in q]
    for j in js:
        assert j in CFG["riviste"], j


def test_query_di_base_disgiunte_e_complete():
    # verifica_sigle confronta somma per rivista e unione: le query devono essere disgiunte
    js = [j for q in pipeline.query_base(CFG) for j in q]
    assert len(js) == len(set(js))
    assert {"A", "B", "C"} <= set(CFG["query"])
    # ogni rivista con un tier è recuperata da almeno una query di base; Liver Int e Surg Innov
    # sono in whitelist solo per il tier, come prima del 16/11/2026
    assert set(CFG["riviste"]) - set(js) <= {"Liver Int", "Surg Innov"}


def test_supplementari_dentro_il_recupero_di_base():
    js = {j for q in pipeline.query_base(CFG) for j in q}
    for area, lista in CFG["query"]["supplementare"].items():
        assert set(lista) <= js, area


def test_riviste_aggiunte_16_11_hanno_prefisso_doi():
    for j in CFG["query"]["C"]:
        assert j in rules.DOI_PREFISSI, j


def test_ann_surg_treat_res_non_e_tier_1():
    assert CFG["riviste"]["Ann Surg Treat Res"] == 3


def test_seen_dir_legge_documenti_nudi_e_incapsulati(tmp_path):
    import json
    (tmp_path / "edizioni").mkdir()
    (tmp_path / "edizioni" / "a.json").write_text(json.dumps(
        {"data": "2026-11-08", "articoli": [{"pmid": "111"}, {"pmid": "222"}]}))
    (tmp_path / "edizioni" / "b.json").write_text(json.dumps(
        {"data": {"data": "2026-11-09", "articoli": [{"pmid": 333}]}}))
    (tmp_path / "edizioni" / "c.json").write_text(json.dumps({"data": "2026-11-10", "articoli": []}))
    assert pipeline.leggi_seen_dir(tmp_path) == {"111", "222", "333"}


# --- DOI: errore del 05/10/2026 ------------------------------------------------------------
XML = """<PubmedArticle><MedlineCitation><PMID>9</PMID>
<Article><Journal><Title>Annals of surgical oncology</Title></Journal>
<ArticleTitle>T</ArticleTitle><ELocationID EIdType="doi">10.1245/s10434-026-1</ELocationID>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article><MedlineJournalInfo><MedlineTA>Ann Surg Oncol</MedlineTA></MedlineJournalInfo>
</MedlineCitation><PubmedData>
<ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">10.1200/JCO.99</ArticleId>
</ArticleIdList></Reference></ReferenceList>
<ArticleIdList><ArticleId IdType="pubmed">9</ArticleId></ArticleIdList>
</PubmedData></PubmedArticle>"""


def test_doi_mai_dalle_citazioni():
    r = fetch.parse_article(etree.fromstring(XML))
    assert r["doi"] == "10.1245/s10434-026-1"
    assert rules.doi_plausibile(r)
    r["doi"] = "10.1200/JCO.99"
    assert not rules.doi_plausibile(r)


def test_chemioipertermia_intratoracica_fuori_dal_colon_retto():
    # caso del 16/11/2026: CRS + HITHOC per tumori epiteliali timici finiva in colon-retto
    _, cl = score(rec("Cytoreductive Surgery with or without Hyperthermic Intrathoracic "
                      "Chemotherapy for Thymic Epithelial Tumors"), "colon-retto")
    assert cl["area"] != "colon-retto"


# --- 18/11/2026: penalità per tipo di testo e termini peritoneali ----------------------------
CHILO = ("A 55 year old woman presented with a recurrent mid-rectal sessile polyp with at least "
         "high-grade dysplasia, having previously undergone transanal minimally invasive surgery. "
         "She proceeded to elective laparoscopic ultralow anterior resection with covering loop "
         "ileostomy. On postoperative day 3, drain output became milky.")


def test_case_report_riconosciuto_dall_abstract_e_penalizzato():
    # PMID 43042530: nessun PublicationType «Case Reports», nessun «case report» nel titolo
    r = rec("Chyle Leak Following Laparoscopic Ultralow Anterior Resection for Recurrent Rectal "
            "Polyp.", abstract=CHILO, rivista="Dis Colon Rectum")
    assert "case_report" in r["segnali"]
    p = rules.punteggio(r, 2.0, 3, NOW, CFG)
    r["segnali"] = []
    assert p["score"] == pytest.approx(rules.punteggio(r, 2.0, 3, NOW, CFG)["score"] * 0.75, abs=0.1)


def test_studio_clinico_non_e_case_report():
    r = rec("Robotic TEP and testicular morbidity",
            abstract="BACKGROUND: We compared 484 patients. A 30-day outcome was assessed. " * 3)
    assert "case_report" not in r["segnali"]


def test_revisione_narrativa_penalizzata_ma_non_la_meta_analisi_indicizzata_come_review():
    # PMID 43044915 (Gastroenterology, solo «Review») vs PMID 43039755 (NMA indicizzata «Review»)
    narr = rec("Serrated neoplasia of the colorectum: updates on pathology and clinical management.",
               abstract="Serrated neoplasia represents an increasingly recognized pathway. " * 5,
               rivista="Gastroenterology", tipi=("Journal Article", "Review"))
    nma = rec("Linear, circular and hand-sewn gastrojejunostomy: a systematic review and network "
              "meta-analysis", rivista="Surg Obes Relat Dis", tipi=("Journal Article", "Review"))
    assert "revisione_narrativa" in narr["segnali"]
    assert "revisione_narrativa" not in nma["segnali"]
    assert rules.punteggio(narr, 2.0, 3, NOW, CFG)["penalita_tipo"] == 0.85
    assert rules.punteggio(nma, 2.0, 3, NOW, CFG)["penalita_tipo"] == 1.0


def test_carcinosi_gastrica_non_finisce_in_colon_retto():
    # PMID 43044526, «PERISCOPE II: lessons learned»: 2,4 punti peritoneali contro 2,0 gastrici
    _, cl = score(rec("The PERISCOPE II study in patients with gastric cancer and limited "
                      "peritoneal metastases: lessons learned.",
                      abstract="Cytoreductive surgery with HIPEC for gastric cancer with limited "
                               "peritoneal metastases versus systemic therapy; gastrectomy. " * 2,
                      rivista="Eur J Surg Oncol"), "eso-gastrico")
    assert cl["punteggi_aree"]["colon-retto"] == 0
    assert cl["area"] == "eso-gastrico"


def test_carcinosi_colorettale_resta_in_colon_retto():
    _, cl = score(rec("Cytoreductive surgery and HIPEC for colorectal peritoneal metastases"),
                  "colon-retto")
    assert cl["area"] == "colon-retto"
    assert {"HIPEC", "cytoreductive", "peritoneal metastases"} <= set(cl["termini"])


def test_case_control_non_e_case_report():
    # PMID 43035620: «A Case-Control Analysis» agganciava '\ba case\b' del titolo
    assert "case_report" not in rec("Post-bariatric hypoglycaemia: A Case-Control Analysis")["segnali"]
    assert "case_report" in rec("Jejunal perforation after pancreatoduodenectomy: a case report")["segnali"]


def test_studio_originale_indicizzato_come_review_non_e_narrativo():
    # PMID 43013967: coorte di 253 pazienti con abstract strutturato, PublicationType «Review»
    r = rec("Time-dependent prognostic value of preoperative CA19-9 after resection",
            abstract="BACKGROUND: x.\nMETHODS: retrospective cohort of 253 patients.\nRESULTS: y.",
            tipi=("Journal Article", "Review"))
    assert "revisione_narrativa" not in r["segnali"]


# --- 19/11/2026: confine eso-gastrico per i termini deboli ---------------------------------
def test_tumore_della_colecisti_con_invasione_duodenale_va_in_hpb():
    # PMID 43049805: 0,7 punti eso-gastrici da 'direct duodenal invasion' contro 0,5 HPB
    _, cl = score(rec("Stage-tailored role of extrahepatic bile duct resection in gallbladder "
                      "cancer: limited value in T2 disease",
                      abstract="EBDR was selectively performed based on lymph node metastasis, "
                               "positive cystic duct margins, or direct duodenal invasion. " * 2,
                      rivista="Langenbecks Arch Surg"), "hpb")
    assert cl["punteggi_aree"]["eso-gastrico"] == 0
    assert cl["area"] == "hpb"


def test_varici_da_ipertensione_portale_non_sono_eso_gastrico():
    _, cl = score(rec("TIPS versus endoscopic therapy for variceal bleeding in cirrhosis",
                      abstract="Patients with cirrhosis and variceal bleeding after hepatectomy. " * 2),
                  "hpb")
    assert cl["punteggi_aree"]["eso-gastrico"] == 0


def test_termini_deboli_restano_con_ancora_esogastrica():
    _, cl = score(rec("Duodenal switch versus Roux-en-Y gastric bypass in severe obesity"),
                  "eso-gastrico")
    assert cl["area"] == "eso-gastrico"
    assert "duodenal" in cl["termini"]
    _, cl = score(rec("Gastroesophageal variceal bleeding: gastric varices after sleeve"),
                  "eso-gastrico")
    assert "variceal" in cl["termini"]


# --- 24/11/2026: resoconti di congresso e bacino della proctologia ----------------------------
def test_resoconto_di_congresso_marcato_e_penalizzato():
    # PMID 43072058: «Take-home messages from the 2025 15th PSOGI congress», 57,7, rank 2
    r = rec("Key updates on Peritoneal Surface Oncology: Take-home messages from the 2025 15th "
            "PSOGI congress.", rivista="Eur J Surg Oncol")
    assert "sintesi_congresso" in r["segnali"]
    p = rules.punteggio(r, 2.0, 3, NOW, CFG)
    assert p["penalita_tipo"] == 0.85
    r["segnali"] = []
    assert p["score"] == pytest.approx(rules.punteggio(r, 2.0, 3, NOW, CFG)["score"] * 0.85, abs=0.1)


@pytest.mark.parametrize("titolo", [
    "Consensus conference on the management of rectal cancer: summary of recommendations",
    "Outcomes of TaTME presented at the ESCP meeting: a multicentre cohort",
    "Highlights of robotic hepatectomy in 300 patients",
])
def test_consenso_e_studi_non_sono_resoconti(titolo):
    assert "sintesi_congresso" not in rec(titolo)["segnali"]


def test_grafia_britannica_conta_per_la_proctologia():
    _, uk = score(rec("Haemorrhoidal artery ligation versus haemorrhoidectomy and faecal "
                      "incontinence", rivista="Colorectal Dis"), "proctologia")
    _, us = score(rec("Hemorrhoidal artery ligation versus hemorrhoidectomy and fecal "
                      "incontinence", rivista="Dis Colon Rectum"), "proctologia")
    assert uk["area"] == us["area"] == "proctologia"
    assert uk["punteggi_aree"]["proctologia"] == us["punteggi_aree"]["proctologia"]


def test_j_anus_rectum_colon_nel_recupero_e_nella_supplementare():
    assert CFG["riviste"]["J Anus Rectum Colon"] == 3
    assert "J Anus Rectum Colon" in CFG["query"]["supplementare"]["proctologia"]
    assert rules.doi_plausibile({"rivista_sigla": "J Anus Rectum Colon",
                                 "doi": "10.23922/jarc.2026-039"})


def test_riviste_aggiunte_27_11_per_la_proctologia():
    assert CFG["riviste"]["J Crohns Colitis"] == 2
    assert CFG["riviste"]["J Surg Res"] == 3
    for j in ("J Crohns Colitis", "J Surg Res"):
        assert j in CFG["query"]["C"]
        assert j in CFG["query"]["supplementare"]["proctologia"]
    assert rules.doi_plausibile({"rivista_sigla": "J Crohns Colitis",
                                 "doi": "10.1093/ecco-jcc/jjag199"})
    assert rules.doi_plausibile({"rivista_sigla": "J Surg Res",
                                 "doi": "10.1016/j.jss.2026.10.003"})
    _, r = score(rec("Microfragmented autologous adipose tissue for perianal fistula in Crohn's "
                     "disease: randomized trial", rivista="J Crohns Colitis"), "proctologia")
    assert r["area"] == "proctologia"
