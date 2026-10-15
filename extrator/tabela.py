"""Extração da tabela "Descrição Analítica do Lote" (pontos, distância, azimute, E, N).

Estratégia:
  1. Localiza linhas e colunas da tabela pela projeção da tinta na imagem binarizada.
  2. Faz OCR de cada coluna separadamente, em várias binarizações (variantes),
     com lista restrita de caracteres. Cada célula fica com vários candidatos.
  3. Escolhe os candidatos usando a redundância geométrica: a distância e o
     azimute de cada lado podem ser recalculados a partir das coordenadas.
"""

import re
import itertools
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .ocr import render, binarize, ocr_words
from . import geo

DPI = 300
VARIANTES = [(1.0, 170), (1.5, 185), (0.6, 150), (0.0, 140)]
WL_PONTO = "-c tessedit_char_whitelist=0123456789-MP"
WL_NUM = "-c tessedit_char_whitelist=0123456789."
WL_AZ = "-c tessedit_char_whitelist=0123456789"

GAP_COLUNA = 45  # px a 300 DPI: separa colunas (espaço entre palavras do azimute ~33 px)
LARG_MIN_COLUNA = 50


@dataclass
class Linha:
    ponto_a: str
    ponto_b: str
    distancia: float
    azimute: float  # graus decimais
    e: float
    n: float
    status: str = "OK"
    obs: list = field(default_factory=list)


# ---------------------------------------------------------------- layout

def _runs(on):
    """Lista de (valor, início, fim) de sequências iguais num vetor booleano."""
    out, x, w = [], 0, len(on)
    while x < w:
        x2 = x
        while x2 < w and on[x2] == on[x]:
            x2 += 1
        out.append((bool(on[x]), x, x2))
        x = x2
    return out


def _segmentos(on, gap_min, larg_min):
    """Agrupa trechos com tinta separados por menos de gap_min; descarta trechos estreitos."""
    segs = [[x0, x1] for v, x0, x1 in _runs(on) if v]
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < gap_min:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [(a, b) for a, b in merged if b - a >= larg_min]


def _linhas_ancora(img_bin):
    """Faixas verticais (y0, y1) das linhas que terminam com uma coordenada N."""
    ws = ocr_words(img_bin, psm=6, lang="eng", extra="-c tessedit_char_whitelist=0123456789.-MP")
    linhas = {}
    for w in ws:
        linhas.setdefault(w.line, []).append(w)
    out = []
    for l in linhas.values():
        txt = "".join(w.text for w in sorted(l, key=lambda w: w.x0))
        if re.search(r"\d{6,8}[.\-,]?\d\d\D{0,3}$", txt) and re.search(r"\d-\d", txt):
            out.append((min(w.y0 for w in l), max(w.y1 for w in l)))
    return sorted(out)


def detectar_layout(img_bin):
    """Retorna (linhas, colunas): faixas y das linhas da tabela e faixas x das colunas."""
    a = np.array(img_bin) < 128
    ancoras = _linhas_ancora(img_bin)
    if len(ancoras) < 2:
        return [], []
    altura = int(np.median([y1 - y0 for y0, y1 in ancoras]))

    # Colunas: tinta acumulada nas faixas das linhas; uma linha vertical (dobra do papel)
    # aparece em quase toda a altura e é ignorada.
    mask = np.zeros(a.shape[0], bool)
    for y0, y1 in ancoras:
        mask[y0:y1] = True
    band = a[mask]
    ink = band.sum(0)
    ink[ink > 0.6 * band.shape[0]] = 0
    colunas = _segmentos(ink > 0, GAP_COLUNA, LARG_MIN_COLUNA)
    if len(colunas) < 5:
        return [], []

    # Linhas: a impressora avança sempre o mesmo passo, então ajustamos uma grade
    # regular (y = y0 + k*passo) aos centros das linhas âncora. Isso recupera
    # linhas que o OCR âncora não reconheceu.
    centros = np.array([(y0 + y1) / 2 for y0, y1 in ancoras])
    difs = np.diff(centros)
    passo = float(np.median(difs[difs > 0.6 * altura])) if len(difs) else altura * 1.5
    for _ in range(2):
        ks = np.round((centros - centros[0]) / passo)
        if len(set(ks)) > 1:
            passo, y_ini = np.polyfit(ks, centros, 1)
        else:
            y_ini = centros[0]
    ks = np.round((centros - y_ini) / passo).astype(int)
    kmin, kmax = ks.min(), ks.max()

    nx0, nx1 = colunas[-1]
    px0, px1 = colunas[0]

    def tem_tinta(k):
        yc = y_ini + k * passo
        y0, y1 = int(yc - altura / 2), int(yc + altura / 2)
        if y0 < 0 or y1 > a.shape[0]:
            return False
        return a[y0:y1, nx0:nx1].sum() > 200 and a[y0:y1, px0:px1].sum() > 200

    while tem_tinta(kmin - 1):
        kmin -= 1
    while tem_tinta(kmax + 1):
        kmax += 1
    linhas = []
    for k in range(kmin, kmax + 1):
        yc = y_ini + k * passo
        linhas.append((int(yc - passo / 2), int(yc + passo / 2)))
    return linhas, colunas


# ---------------------------------------------------------------- OCR por coluna

def _ocr_coluna(img, x0, x1, linhas, wl, margem=12):
    """OCR de uma coluna; devolve o texto de cada linha (ou '')."""
    y0 = max(0, linhas[0][0] - 20)
    y1 = min(img.height, linhas[-1][1] + 20)
    crop = img.crop((max(0, x0 - margem), y0, min(img.width, x1 + margem), y1))
    ws = ocr_words(crop, psm=6, lang="eng", extra=wl)
    textos = [[] for _ in linhas]
    for w in ws:
        yc = w.yc + y0
        best = min(range(len(linhas)), key=lambda i: abs((linhas[i][0] + linhas[i][1]) / 2 - yc))
        ly0, ly1 = linhas[best]
        if ly0 - 15 <= yc <= ly1 + 15:
            textos[best].append(w)
    return [" ".join(w.text for w in sorted(t, key=lambda w: w.x0)) for t in textos]


# ---------------------------------------------------------------- candidatos

def _delecoes(s, n):
    """Variações de s com tamanho n removendo dígitos (OCR costuma duplicar dígitos)."""
    if len(s) == n:
        return [s]
    if len(s) == n + 1:
        return list(dict.fromkeys(s[:i] + s[i + 1:] for i in range(len(s))))
    return []


def cand_ponto(txt):
    t = re.sub(r"[^MP0-9\-]", "", txt.upper())
    m = re.search(r"([MP4]?)-*(\d{5,8})-+(\d)", t)
    if not m:
        return []
    letra = {"M": "M", "4": "M", "P": "P"}.get(m.group(1), "")
    return [(letra, d, m.group(3)) for d in _delecoes(m.group(2), 6)]


def cand_num(txt, inteiros):
    """Candidatos para número com 'inteiros' dígitos antes do ponto e 2 decimais."""
    t = re.sub(r"[^0-9.]", "", txt.replace(",", ".").replace("-", "."))
    out = []
    m = re.fullmatch(r"\.?(\d+)\.+(\d{2,3})\.?", t)
    if m:
        ints, decs = m.group(1), m.group(2)
        for i in _delecoes(ints, inteiros):
            for d in _delecoes(decs, 2):
                out.append(float(f"{i}.{d}"))
    else:
        dig = re.sub(r"\D", "", t)
        for d in _delecoes(dig, inteiros + 2):
            out.append(float(f"{d[:-2]}.{d[-2:]}"))
    return out


def cand_dist(txt):
    t = re.sub(r"[^0-9.]", "", txt.replace(",", ".").replace("-", "."))
    out = []
    m = re.fullmatch(r"\.?(\d{1,5})\.+(\d{2,3})\.?", t)
    if m:
        for d in _delecoes(m.group(2), 2):
            out.append(float(f"{m.group(1)}.{d}"))
    elif re.fullmatch(r"\d{3,7}", t):
        out.append(float(f"{t[:-2]}.{t[-2:]}"))
    return out


def cand_az(txt):
    toks = re.findall(r"\d+", txt)
    out = []
    if len(toks) == 3:
        opts = [tuple(int(x) for x in toks)]
    else:
        dig = "".join(toks)
        opts = [(int(dig[:-4] or 0), int(dig[-4:-2]), int(dig[-2:]))] if 5 <= len(dig) <= 7 else []
        if len(dig) == 8:  # um dígito a mais
            for d in _delecoes(dig, 7):
                opts.append((int(d[:-4]), int(d[-4:-2]), int(d[-2:])))
    for g, m, s in opts:
        if g < 360 and m < 60 and s < 60:
            out.append(geo.dms_to_deg(g, m, s))
    return out


# ---------------------------------------------------------------- solver geométrico

def _tol_dist(d):
    # distância impressa = valor real arredondado; coordenadas arredondadas a cm
    return 0.015 + 1e-5 * d


def _tol_az(d):
    # arredondamento de 1" + efeito do arredondamento das coordenadas (cm) em lados curtos
    return 2.0 + 206265 * 0.015 / max(d, 0.01)


def _confere(p, q, dists, azs):
    """Pontuação do lado p->q contra os candidatos lidos: 0, 1 ou 2."""
    d, az = geo.dist_az(p[0], p[1], q[0], q[1])
    s = 0
    if any(abs(d - x) <= _tol_dist(d) for x in dists):
        s += 1
    if any(geo.az_diff(az, x) <= _tol_az(d) for x in azs):
        s += 1
    return s


def resolver(cel):
    """cel: lista de dicts por linha com Counters de candidatos -> lista[Linha], avisos."""
    n = len(cel)
    avisos = []

    # Coordenadas: candidatos (E, N) por ponto, ordenados por votos; filtra valores fora da massa.
    medE = np.median([c["e"].most_common(1)[0][0] for c in cel if c["e"]] or [0])
    medN = np.median([c["n"].most_common(1)[0][0] for c in cel if c["n"]] or [0])
    cands = []
    for c in cel:
        es = [(v, k) for v, k in c["e"].items() if abs(v - medE) < 20000]
        ns = [(v, k) for v, k in c["n"].items() if abs(v - medN) < 20000]
        combo = sorted(((ev, nv, ek + nk) for (ev, ek), (nv, nk) in itertools.product(es, ns)),
                       key=lambda t: -t[2])
        cands.append(combo[:25])

    escolha = [c[0][:2] if c else None for c in cands]

    def score_ponto(i, p):
        s = 0
        if escolha[i - 1] is not None:
            s += _confere(escolha[i - 1], p, cel[i - 1]["dist"], cel[i - 1]["az"])
        if escolha[(i + 1) % n] is not None:
            s += _confere(p, escolha[(i + 1) % n], cel[i]["dist"], cel[i]["az"])
        return s

    for _ in range(3):
        mudou = False
        for i in range(n):
            if not cands[i]:
                continue
            melhor = max(cands[i], key=lambda t: (score_ponto(i, t[:2]), t[2]))
            if melhor[:2] != escolha[i]:
                escolha[i] = melhor[:2]
                mudou = True
        if not mudou:
            break

    # Pontos sem confirmação: recalcula a partir dos vizinhos (poligonal pelos dois lados)
    recalculados = set()
    for i in range(n):
        ant, prox = escolha[i - 1], escolha[(i + 1) % n]
        if escolha[i] is not None and score_ponto(i, escolha[i]) >= 3:
            continue
        if ant is None or prox is None:
            continue
        melhor = None
        for d1, a1 in itertools.product(cel[i - 1]["dist"], cel[i - 1]["az"]):
            p = geo.polar(ant[0], ant[1], d1, a1)
            for d2, a2 in itertools.product(cel[i]["dist"], cel[i]["az"]):
                q = geo.polar(prox[0], prox[1], d2, (a2 + 180) % 360)
                err = abs(p[0] - q[0]) + abs(p[1] - q[1])
                if err < 0.06 and (melhor is None or err < melhor[0]):
                    melhor = (err, ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
        if melhor:
            antigo = escolha[i]
            escolha[i] = (round(melhor[1][0], 2), round(melhor[1][1], 2))
            if antigo != escolha[i]:
                recalculados.add(i)

    # Nomes dos pontos: votos da coluna A da linha i e da coluna B da linha i-1,
    # contados caractere a caractere (um dígito errado não derruba a leitura inteira).
    # Empates são decididos pela frequência do dígito na mesma posição nos demais pontos.
    prior = [Counter() for _ in range(6)]
    for c in cel:
        for (_, d, _), k in (c["pa"] + c["pb"]).items():
            for j, ch in enumerate(d):
                prior[j][ch] += k
    nomes = []
    for i in range(n):
        votos = cel[i]["pa"] + cel[i - 1]["pb"]
        if not votos:
            nomes.append(f"PONTO-{i + 1}")
            avisos.append(f"Linha {i + 1}: nome do ponto ilegível")
            continue
        letras, verif = Counter(), Counter()
        pos = [Counter() for _ in range(6)]
        for (l, d, v), k in votos.items():
            if l:
                letras[l] += k
            verif[v] += k
            for j, ch in enumerate(d):
                pos[j][ch] += k
        l = letras.most_common(1)[0][0] if letras else "P"
        d = "".join(max(c, key=lambda ch: (c[ch], prior[j][ch])) for j, c in enumerate(pos))
        nomes.append(f"{l}-{d}-{verif.most_common(1)[0][0]}")

    linhas = []
    for i in range(n):
        p, q = escolha[i], escolha[(i + 1) % n]
        if p is None:
            linhas.append(Linha(nomes[i], nomes[(i + 1) % n], float("nan"), float("nan"),
                                float("nan"), float("nan"), "REVISAR", ["coordenada ilegível"]))
            continue
        lin = Linha(nomes[i], nomes[(i + 1) % n], float("nan"), float("nan"), p[0], p[1])
        if i in recalculados:
            lin.status = "CORRIGIDO"
            lin.obs.append("coordenada recalculada pelos lados vizinhos")
        if q is None:
            lin.status = "REVISAR"
            linhas.append(lin)
            continue
        d, az = geo.dist_az(p[0], p[1], q[0], q[1])
        dl = [x for x in cel[i]["dist"] if abs(d - x) <= _tol_dist(d)]
        al = [x for x in cel[i]["az"] if geo.az_diff(az, x) <= _tol_az(d)]
        lin.distancia = min(dl, key=lambda x: (abs(x - d), -cel[i]["dist"][x])) if dl else round(d, 2)
        lin.azimute = min(al, key=lambda x: (geo.az_diff(x, az), -cel[i]["az"][x])) if al else az
        if not dl or not al:
            faltou = [nm for nm, ok in (("distância", dl), ("azimute", al)) if not ok]
            lin.obs.append(f"{' e '.join(faltou)} recalculado(s) pelas coordenadas (OCR ilegível)")
            if lin.status == "OK":
                lin.status = "CALCULADO"
        linhas.append(lin)

    # Um ponto que não fecha com nenhum dos dois lados indica erro não resolvido
    for i in range(n):
        if escolha[i] is not None and score_ponto(i, escolha[i]) <= 1 and i not in recalculados:
            linhas[i].status = "REVISAR"
            linhas[i].obs.append("coordenada não confirmada pelos lados vizinhos")
    return linhas, avisos


# ---------------------------------------------------------------- API

def extrair(page, log=lambda m: None):
    """Extrai a tabela da página. Retorna (linhas, avisos)."""
    gray = render(page, DPI)
    variantes = [binarize(gray, b, t) for b, t in VARIANTES]
    linhas_y, colunas = detectar_layout(variantes[0])
    if not linhas_y:
        linhas_y, colunas = detectar_layout(variantes[1])
    if not linhas_y:
        return [], ["não foi possível localizar as linhas/colunas da tabela"]

    pa, pb, dist, e, n = colunas[0], colunas[1], colunas[2], colunas[-2], colunas[-1]
    az = (colunas[3][0], colunas[-3][1]) if len(colunas) >= 6 else None
    log(f"  tabela: {len(linhas_y)} linhas, {len(colunas)} colunas")

    cel = [{k: Counter() for k in ("pa", "pb", "dist", "az", "e", "n")} for _ in linhas_y]
    for img in variantes:
        cols = {
            "pa": _ocr_coluna(img, *pa, linhas_y, WL_PONTO),
            "pb": _ocr_coluna(img, *pb, linhas_y, WL_PONTO),
            "dist": _ocr_coluna(img, *dist, linhas_y, WL_NUM),
            "e": _ocr_coluna(img, *e, linhas_y, WL_NUM),
            "n": _ocr_coluna(img, *n, linhas_y, WL_NUM),
        }
        if az:
            cols["az"] = _ocr_coluna(img, *az, linhas_y, WL_AZ)
        for i in range(len(linhas_y)):
            for v in cand_ponto(cols["pa"][i]):
                cel[i]["pa"][v] += 1
            for v in cand_ponto(cols["pb"][i]):
                cel[i]["pb"][v] += 1
            for v in cand_dist(cols["dist"][i]):
                cel[i]["dist"][v] += 1
            for v in cand_num(cols["e"][i], 6):
                cel[i]["e"][v] += 1
            for v in cand_num(cols["n"][i], 7):
                cel[i]["n"][v] += 1
            if az:
                for v in cand_az(cols["az"][i]):
                    cel[i]["az"][v] += 1

    # Descarta linhas sem nenhuma coordenada lida (ruído detectado como linha)
    cel = [c for c in cel if c["e"] or c["n"]]
    return resolver(cel)
