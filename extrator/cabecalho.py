"""Classificação de páginas e leitura dos dados do lote (município, distrito, gleba, lote)."""

import re
import difflib
import unicodedata
from collections import Counter

MUNICIPIOS_SE = [
    "Amparo de São Francisco", "Aquidabã", "Aracaju", "Arauá", "Areia Branca",
    "Barra dos Coqueiros", "Boquim", "Brejo Grande", "Campo do Brito", "Canhoba",
    "Canindé de São Francisco", "Capela", "Carira", "Carmópolis", "Cedro de São João",
    "Cristinápolis", "Cumbe", "Divina Pastora", "Estância", "Feira Nova", "Frei Paulo",
    "Gararu", "General Maynard", "Gracho Cardoso", "Ilha das Flores", "Indiaroba",
    "Itabaiana", "Itabaianinha", "Itabi", "Itaporanga d'Ajuda", "Japaratuba", "Japoatã",
    "Lagarto", "Laranjeiras", "Macambira", "Malhada dos Bois", "Malhador", "Maruim",
    "Moita Bonita", "Monte Alegre de Sergipe", "Muribeca", "Neópolis",
    "Nossa Senhora Aparecida", "Nossa Senhora da Glória", "Nossa Senhora das Dores",
    "Nossa Senhora de Lourdes", "Nossa Senhora do Socorro", "Pacatuba", "Pedra Mole",
    "Pedrinhas", "Pinhão", "Pirambu", "Poço Redondo", "Poço Verde", "Porto da Folha",
    "Propriá", "Riachão do Dantas", "Riachuelo", "Ribeirópolis", "Rosário do Catete",
    "Salgado", "Santa Luzia do Itanhy", "Santana do São Francisco", "Santa Rosa de Lima",
    "Santo Amaro das Brotas", "São Cristóvão", "São Domingos", "São Francisco",
    "São Miguel do Aleixo", "Simão Dias", "Siriri", "Telha", "Tobias Barreto",
    "Tomar do Geru", "Umbaúba",
]


def sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def norm(s: str) -> str:
    return sem_acento(s).upper()


_MUN_NORM = {re.sub(r"[^A-Z ]", "", norm(m)): m for m in MUNICIPIOS_SE}


# ---------------------------------------------------------------- classificação

_UTM_E = re.compile(r"\b7\d{5}[.,]\d{2}\b")
_UTM_N = re.compile(r"\b8\d{6}[.,]\d{2}\b")


def score_tabela(texto: str) -> float:
    u = norm(texto)
    s = 0.0
    for k, w in (("ANALITICA", 4), ("ANAL", 1), ("GEOGRAFICAS", 2), ("COORDENADAS", 1),
                 ("AZIMUTE", 1), ("DISTANCIA", 1), ("GEODATA", 1), ("REMANESCENTE", 1)):
        if k in u:
            s += w
    s += 0.5 * min(len(_UTM_E.findall(u)) + len(_UTM_N.findall(u)), 20)
    return s


def score_memorial(texto: str) -> float:
    u = norm(texto)
    s = 0.0
    for k, w in (("MEMORIAL", 2), ("DISTRITO", 2), ("MUNIC", 1), ("GLEBA", 1),
                 ("LATITUDE", 1), ("PARTINDO", 2), ("CHEGA", 1), ("DESCRI", 1)):
        if k in u:
            s += w
    return s


# ---------------------------------------------------------------- campos

def _limpa(s: str) -> str:
    s = re.sub(r"[^A-Za-zÀ-ÿ0-9 .\-/']", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-'")
    # descarta "sujeira" de 1 caractere no fim (respingos lidos pelo OCR)
    toks = s.split(" ")
    while len(toks) > 1 and len(toks[-1].strip(".")) <= 1:
        toks.pop()
    return " ".join(toks)


def campos_memorial(texto: str) -> dict:
    """Extrai campos do cabeçalho do memorial (antigo Convênio Incra e Cohidro)."""
    out = {}
    linhas = texto.splitlines()
    for i, ln in enumerate(linhas):
        u = norm(ln)
        m = re.search(r"MUNIC\w*\W+(.+)$", u)
        if m and "municipio" not in out:
            out["municipio"] = _limpa(m.group(1))
        m = re.search(r"DISTRITO\w*\W*(.*)$", u)
        if m and "distrito" not in out:
            valor = _limpa(m.group(1))
            # remove letras soltas que o OCR gruda no início ("t", "!t")
            valor = re.sub(r"^[A-Z]\b ?", "", valor) if len(valor) > 2 and valor[1:2] == " " else valor
            if not re.search(r"DESCRI|PERIMETRO", valor):
                out["distrito"] = valor
        m = re.search(r"[GB6]LE[BH8][AS]\w*?\W+(?:[A-Z]\s+)?([0-9BGS]{1,2}\s*[-=]\s*[A-Z']+|[A-Z']{3,})", u)
        if m and "gleba" not in out:
            out["gleba"] = m.group(1)
        m = re.search(r"^\W*LOTE\w*\W+[0-9BGS]{1,2}\s*/\s*(\d{1,5}[A-Z]?)\b", u)
        if m and "lote" not in out:
            out["lote"] = m.group(1)
        uu = re.sub(r"[.,]{2,}", ".", u)
        m = re.search(r"PER\w*METRO\W*\(?M\)?\W*(\d{1,6}[.,]\d{2})\b", uu)
        if m and "perimetro" not in out:
            out["perimetro"] = float(m.group(1).replace(",", "."))
        m = re.search(r"AREA\W*\(?HA\)?\W*(\d{1,4}[.,]\d{4})\b", uu)
        if m and "area" not in out:
            out["area"] = float(m.group(1).replace(",", "."))
    return out


def campos_tabela(texto: str) -> dict:
    """Campos da página 'Descrição Analítica'."""
    out = {}
    u = re.sub(r"[.,]{2,}", ".", norm(texto))
    m = re.search(r"[GB6]LE[BH8][AS]\W+(?:[A-Z]\s+)?([0-9BGS]{1,2}\s*[-=]\s*[A-Z']+)", u)
    if m:
        out["gleba"] = m.group(1)
    for m in re.finditer(r"^.*\bLOTE\b(.*)$", u, re.M):
        # "LOTE : 8- 102" -> o número do lote é o último da linha (o ":" às vezes vira "3")
        nums = re.findall(r"\d+", m.group(1))
        if nums and len(nums[-1]) <= 5:
            out["lote"] = nums[-1]
            break
    m = re.search(r"PERIMETR\w*\W+([\d]+[.,]\d{2})", u)
    if m:
        out["perimetro"] = float(m.group(1).replace(",", "."))
    m = re.search(r"\bAREA\W+([\d]+[.,]\d{4})\s*H", u)
    if m:
        out["area"] = float(m.group(1).replace(",", "."))
    return out


def municipio_canonico(txt: str):
    t = re.sub(r"[^A-Z ]", "", norm(txt)).strip()
    if not t:
        return None
    # "JAPARATUBA/PIRAMBU" -> testa cada parte e também o texto inteiro
    partes = [t] + [p.strip() for p in re.split(r"[/ ]{2,}|/", norm(txt)) if p.strip()]
    melhor = None
    for p in partes:
        p = re.sub(r"[^A-Z ]", "", p).strip()
        m = difflib.get_close_matches(p, list(_MUN_NORM), n=1, cutoff=0.7)
        if m:
            r = difflib.SequenceMatcher(None, p, m[0]).ratio()
            if melhor is None or r > melhor[0]:
                melhor = (r, _MUN_NORM[m[0]])
    return melhor[1] if melhor else None


def gleba_canonica(txt: str) -> str:
    t = norm(txt).replace(" ", "").replace("=", "-").replace("'", "")
    m = re.match(r"([0-9BGS]{1,2})-?([A-Z]+)", t)
    if not m:
        return t
    # Fonte matricial: o "8" costuma ser lido como "B" ou "GB"
    num = m.group(1)
    if len(num) == 2 and num[0] == "G" and num[1] in "B8":  # "GB-PIRAJA" = "8-PIRAJA"
        num = num[1]
    num = {"B": "8", "BB": "8", "S": "5", "G": "6"}.get(num, num)
    num = num.replace("B", "8").replace("S", "5").replace("G", "6")
    return f"{num}-{m.group(2)}"


def medoide(valores):
    """Valor mais parecido com os demais (consenso entre leituras ruidosas)."""
    valores = [v for v in valores if v]
    if not valores:
        return ""
    cont = Counter(valores)
    if cont.most_common(1)[0][1] > 1:
        return cont.most_common(1)[0][0]
    return max(valores, key=lambda v: sum(difflib.SequenceMatcher(None, v, w).ratio() for w in valores))


def consolidar(leituras: list[dict], nome_arquivo: str = "") -> dict:
    """Combina leituras de várias páginas/variantes em um único cabeçalho."""
    mun = [municipio_canonico(l["municipio"]) for l in leituras if l.get("municipio")]
    dist = [l["distrito"] for l in leituras if l.get("distrito") is not None]
    gleb = [gleba_canonica(l["gleba"]) for l in leituras if l.get("gleba")]
    lote = [l["lote"].lstrip("0") for l in leituras if l.get("lote")]
    m = re.search(r"LOTE\s*0*(\d+[A-Z]?)", norm(nome_arquivo))
    if m:
        lote.append(m.group(1))
    distrito = medoide([d for d in dist if len(d) >= 3])
    perim = Counter(l["perimetro"] for l in leituras if l.get("perimetro"))
    area = Counter(l["area"] for l in leituras if l.get("area"))
    return {
        "perimetro": perim.most_common(1)[0][0] if perim else None,
        "area": area.most_common(1)[0][0] if area else None,
        "perimetros": list(perim), "areas": list(area),
        "municipio": medoide([m for m in mun if m]) or "",
        "distrito": distrito,
        "gleba": medoide([g for g in gleb if re.match(r"\d+-[A-Z]{3,}", g)]) or medoide(gleb),
        "lote": Counter(lote).most_common(1)[0][0] if lote else "",
    }


def slug(s: str) -> str:
    s = norm(s)
    s = re.sub(r"[^A-Z0-9\-]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def nome_base(cab: dict) -> str:
    partes = [slug(cab.get("municipio") or "SEM_MUNICIPIO"),
              slug(cab.get("distrito") or "SEM_DISTRITO"),
              slug(cab.get("gleba") or "SEM_GLEBA")]
    if cab.get("lote"):
        partes.append(f"LOTE_{slug(cab['lote'])}")
    return "_".join(partes)
