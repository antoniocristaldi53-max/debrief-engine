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
    for j in CFG["query"]["A"] + CFG["query"]["B"]:
        assert j in CFG["riviste"], j


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
