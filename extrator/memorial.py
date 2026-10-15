"""Fallback para lotes sem a página "Descrição Analítica": reconstrói a poligonal
a partir dos azimutes/distâncias (tabela da planta + texto do memorial) e da
latitude/longitude do marco inicial.

O resultado é marcado como ESTIMADO: a forma do lote é confiável quando a
poligonal fecha, mas a posição absoluta depende da lat/long impressa com
precisão de 1" (~30 m).
"""

import re
import math
from collections import Counter

from . import geo
from .cabecalho import norm
from .tabela import Linha

_MAPA = str.maketrans({"O": "0", "Q": "0", "D": "0", "@": "0", "Ø": "0", "B": "8", "S": "5",
                       "I": "1", "L": "1", "|": "1", "Z": "2"})


def _dig(tok: str) -> str:
    return re.sub(r"\D", "", tok.upper().translate(_MAPA))


def _sem_simbolos(t: str) -> str:
    # O Tesseract devolve "°" como caractere inválido; vira separador
    return t.replace("�", " ").replace("°", " ").replace("º", " ")


def _delecoes(s, n):
    if len(s) <= n:
        return [s]
    if len(s) == n + 1:
        return list(dict.fromkeys(s[:i] + s[i + 1:] for i in range(len(s))))
    return []


PESO_ALT = 0.2  # peso de uma leitura alternativa (8 -> 0)


def _troca_8_0(s):
    """A planta usa zero cortado (Ø), que o OCR lê como 8: gera as alternativas."""
    out = {s}
    for i, ch in enumerate(s):
        if ch == "8":
            out |= {x[:i] + "0" + x[i + 1:] for x in list(out)}
    return out


def _az(g, m, s):
    if g < 360 and m < 60 and s < 60:
        return geo.dms_to_deg(g, m, s)
    return None


def _dist_cands(tok: str, troca=False):
    t = tok.upper().translate(_MAPA).replace(",", ".")
    t = re.sub(r"[^0-9.]", "", t)
    m = re.match(r"\.*(\d{1,4})\.+(\d{2})", t)
    if not m:
        return {}
    base = f"{m.group(1)}.{m.group(2)}"
    out = {float(x): PESO_ALT for x in (_troca_8_0(base) if troca else {base})}
    out[float(base)] = 1.0
    return out


def _az_cands(txt: str, troca=False):
    """Candidatos de azimute de trechos como "229 59'33", "194 3117" ou "2380 48'21"."""
    grupos = re.findall(r"\d+", _sem_simbolos(txt).upper().translate(_MAPA))
    trincas = []
    if len(grupos) >= 3:
        trincas.append(grupos[:3])
    elif len(grupos) == 2:
        g, r = grupos
        if len(r) == 4:
            trincas.append([g, r[:2], r[2:]])
        elif len(r) == 3:
            trincas += [[g, r[0], r[1:]], [g, r[:2], r[2]]]
    elif len(grupos) == 1 and 5 <= len(grupos[0]) <= 7:
        d = grupos[0]
        trincas.append([d[:-4], d[-4:-2], d[-2:]])
    out = {}
    for g, m, s in trincas:
        for gg in _delecoes(g, 3):
            for mm in _delecoes(m, 2):
                for ss in _delecoes(s, 2):
                    for g2 in (_troca_8_0(gg) if troca else {gg}):
                        for m2 in (_troca_8_0(mm) if troca else {mm}):
                            for s2 in (_troca_8_0(ss) if troca else {ss}):
                                if g2 and m2 and s2:
                                    az = _az(int(g2), int(m2), int(s2))
                                    if az is not None:
                                        peso = 1.0 if (g2, m2, s2) == (gg, mm, ss) else PESO_ALT
                                        k = round(az, 6)
                                        out[k] = max(out.get(k, 0), peso)
    # normaliza: leituras ambíguas dividem o voto
    tot = sum(v for v in out.values() if v == 1.0) or 1
    return {k: v / tot for k, v in out.items()}


# ---------------------------------------------------------------- tabela da planta

_DIST = re.compile(r"(?<![\d.,])(\d{1,4}[.,]\d{2})\d?(?![\d])")
_PONTO = re.compile(r"([MP4][\w@]{1,7}?)-\w")


def lados_planta(words, largura):
    """Lados da tabela da planta a partir das palavras do OCR (com posição).

    Retorna dict {(coluna, y_linha): (ponto_a, [dist], [az])}; a tabela tem duas
    metades (esquerda e direita) lidas de cima para baixo.
    """
    linhas = {}
    for w in words:
        linhas.setdefault(w.line, []).append(w)
    out = {}
    for ws in linhas.values():
        ws.sort(key=lambda w: w.x0)
        txt, xs = "", []
        for w in ws:
            if txt:
                txt += " "
                xs.append(w.x0)
            txt += w.text
            xs += [w.x0] * len(w.text)
        txt = _sem_simbolos(txt)
        yc = sum(w.yc for w in ws) / len(ws)
        for m in _DIST.finditer(txt):
            resto = txt[m.end():m.end() + 18]
            corte = re.search(r'["*]|[A-Za-z]{3,}|\s\d-|\s[B8G]-', resto)
            trecho = resto[:corte.start()] if corte else resto[:12]
            az = _az_cands(trecho, troca=True)
            if not az:
                continue
            col = 0 if xs[m.start()] < largura / 2 else 1
            pts = _PONTO.findall(txt[max(0, m.start() - 30):m.start()])
            nome = pts[-2] if len(pts) >= 2 else (pts[0] if pts else None)
            out[(col, yc)] = (nome, _dist_cands(m.group(1), troca=True), az)
    return out


def _alinhar_planta(leituras, passo):
    """Junta leituras (variantes) da planta pela posição (coluna, linha)."""
    chaves = []
    for lt in leituras:
        for col, y in lt:
            if not any(c == col and abs(y - yy) < passo / 2 for c, yy in chaves):
                chaves.append((col, y))
    chaves.sort()
    lados = []
    for col, y in chaves:
        nomes, ds, azs = Counter(), Counter(), Counter()
        for lt in leituras:
            for (c, yy), (nome, d, a) in lt.items():
                if c == col and abs(y - yy) < passo / 2:
                    if nome:
                        nomes[nome] += 1
                    for x, w in d.items():
                        ds[x] += w
                    for x, w in a.items():
                        azs[x] += w
        lados.append((nomes, ds, azs))
    return lados


# ---------------------------------------------------------------- texto do memorial

_MEMO_LADO = re.compile(
    r"\w{0,2}[zsr]\w{0,3}m\w{0,3}te\W+(.{3,40}?)\s+e\s+\S{0,3}[l1i]\S{0,2}d\S?\s+(\S{3,9}?)\s*m",
    re.I | re.S)


def lados_memorial(texto: str):
    """Lados ([dist], [az]) na ordem do texto do memorial."""
    out = []
    for m in _MEMO_LADO.finditer(texto):
        ang, dist = m.group(1), m.group(2)
        partes = re.split(r"[GC6]?[RB]?ra\w*|M\b|\s+", ang)
        nums = [_dig(p) for p in partes if _dig(p)]
        az = []
        if len(nums) >= 3:
            g, mi, s = nums[0], nums[1], nums[2]
            if len(g) == 4 and g.endswith("6"):  # "1786raus" -> 178 + "Graus"
                g = g[:3]
            # o "S" de segundos costuma virar 8/5: "238" -> 23
            ss = [s[:2]] if len(s) == 3 else ([s[:1], s] if len(s) == 2 and s[1] in "58" else [s])
            for x in ss:
                try:
                    v = _az(int(g), int(mi[:2]), int(x[:2]))
                except ValueError:
                    v = None
                if v is not None:
                    az.append(round(v, 6))
        out.append((_dist_cands(dist), {x: 1 / len(az) for x in az}))
    return out


# ---------------------------------------------------------------- lat/long do marco

def _num_ok(tok: str):
    """Número de um token só se todos os caracteres forem dígitos ou letras recuperáveis."""
    t = re.sub(r"[MS'\"]+$", "", tok.upper())
    if not t or re.search(r"[^0-9OQD@BSILZ|]", t):
        return None
    return t.translate(_MAPA)


def lat_lon(textos):
    """Vota graus/minutos/segundos de latitude e longitude do marco inicial."""
    votos = {k: Counter() for k in ("la_g", "la_m", "la_s", "lo_g", "lo_m", "lo_s")}
    for t in textos:
        u = norm(_sem_simbolos(t))
        # Memorial: "Latitude 10Graus 33M 56S Sul e Longitude 36Graus 48M 56S Oeste"
        m = re.search(r"LATITUDE\W+(\S{1,4}?)\s*[G6C]?RAU\S*\s+(\S{1,4}?)M?\s+(\S{1,4}?)\s+SUL", u)
        if m:
            _vota(votos, "la", m.groups(), 1)
        m = re.search(r"LON\w*\W+(\S{1,4}?)\s*[G6C]?RAU\S*\s+(\S{1,4}?)M?\s+(\S{1,4}?)\s+OES", u)
        if m:
            _vota(votos, "lo", m.groups(), 1)
        # Planta: "Coordenadas do Marco 208-8 : 10°33'56" Sul e 36°48'56" Oeste" (fonte mais limpa)
        m = re.search(r"MARCO.{0,15}:\s*(\S{1,3})\W{1,2}\s*(\S{1,3})\W\s*(\S{1,3})\W{0,2}\s*SU\w*\s*E\s*"
                      r"(\S{1,3})\W{1,2}\s*(\S{1,4})\W\s*(\S{1,3})\W{0,2}\s*OES", u)
        if m:
            _vota(votos, "la", m.groups()[:3], 2)
            _vota(votos, "lo", m.groups()[3:], 2)
    try:
        v = {k: c.most_common(1)[0][0] for k, c in votos.items()}
    except IndexError:
        return None
    lat = -geo.dms_to_deg(v["la_g"], v["la_m"], v["la_s"])
    lon = -geo.dms_to_deg(v["lo_g"], v["lo_m"], v["lo_s"])
    return lat, lon


def _vota(votos, pre, grupo, peso):
    g, m, s = (_num_ok(x) for x in grupo)
    validos = {"la": ("9", "10", "11"), "lo": ("36", "37", "38")}[pre]
    for gg in _delecoes(g or "", 2):
        if gg in validos:
            votos[f"{pre}_g"][int(gg)] += peso
    # dígito a mais inserido pelo OCR ("323" -> "33"): o caractere do meio é o
    # suspeito mais provável; as outras remoções recebem peso menor
    for chave, val in (("m", m), ("s", s)):
        val = val or ""
        if len(val) == 3:
            cands = [(val[0] + val[2], 0.6), (val[1:], 0.2), (val[:2], 0.2)]
        elif val:
            cands = [(val, 1.0)]
        else:
            cands = []
        for c, w in cands:
            if int(c) < 60:
                votos[f"{pre}_{chave}"][int(c)] += peso * w


# ---------------------------------------------------------------- poligonal

def poligonal(lados, perimetro=None, area=None):
    """lados: lista de (Counter dist, Counter az). Escolhe os candidatos que fecham a poligonal."""
    dists = [d for d, _ in lados]
    azs = [a for _, a in lados]
    if not lados or any(not d for d in dists) or any(not a for a in azs):
        return None
    n = len(lados)
    esc_d = [d.most_common(1)[0][0] for d in dists]
    esc_a = [a.most_common(1)[0][0] for a in azs]

    maxd = [max(d.values()) for d in dists]
    maxa = [max(a.values()) for a in azs]

    def custo(ed, ea):
        pts = [(0.0, 0.0)]
        for d, a in zip(ed, ea):
            pts.append(geo.polar(pts[-1][0], pts[-1][1], d, a))
        c = math.hypot(*pts[-1])
        if perimetro:
            c += abs(sum(ed) - perimetro)
        if area:
            c += abs(geo.area_shoelace(pts[:-1]) / 1e4 - area) * 1e4 / max(sum(ed), 1)
        # penaliza escolher leituras com menos votos (0,5 m por voto inteiro de diferença)
        c += 0.5 * sum((maxd[i] - dists[i][d]) / maxd[i] for i, d in enumerate(ed))
        c += 0.5 * sum((maxa[i] - azs[i][a]) / maxa[i] for i, a in enumerate(ea))
        return c

    atual = custo(esc_d, esc_a)
    for _ in range(8):
        melhorou = False
        for i in range(n):
            for d in dists[i]:
                t = esc_d[:i] + [d] + esc_d[i + 1:]
                c = custo(t, esc_a)
                if c < atual - 1e-9:
                    esc_d, atual, melhorou = t, c, True
            for a in azs[i]:
                t = esc_a[:i] + [a] + esc_a[i + 1:]
                c = custo(esc_d, t)
                if c < atual - 1e-9:
                    esc_a, atual, melhorou = t, c, True
        if not melhorou:
            break
    return esc_d, esc_a


def reconstruir(planta_words, largura, passo, textos_memorial, textos_planta, crs,
                perimetro=None, area=None, log=lambda m: None):
    """Retorna (linhas, avisos) com coordenadas estimadas, ou ([], avisos).

    planta_words: lista (uma por variante) de listas de palavras OCR da planta.
    """
    avisos = []
    leituras = [lados_planta(ws, largura) for ws in planta_words]
    lados = _alinhar_planta([l for l in leituras if l], passo)
    n = len(lados)
    if n < 3:
        return [], ["não foi possível ler a tabela de lados da planta"]
    # O memorial entra como voto extra. O OCR do texto pula lados, então cada lado do
    # memorial é casado (em ordem) com o próximo lado compatível da planta.
    def compativel(lado, d, a):
        _, ds, azs = lado
        ok_d = any(abs(x - y) < 0.02 for x in d for y in ds)
        ok_a = any(geo.az_diff(x, y) < 120 for x in a for y in azs)
        return ok_d or ok_a

    for t in textos_memorial:
        j = 0
        for d, a in lados_memorial(t):
            for i in range(j, min(j + 3, n)):
                if compativel(lados[i], d, a):
                    _, ds, azs = lados[i]
                    for x, w in d.items():
                        ds[x] += w
                    for x, w in a.items():
                        azs[x] += w
                    j = i + 1
                    break
    res = poligonal([(ds, azs) for _, ds, azs in lados], perimetro, area)
    if not res:
        return [], ["não foi possível ler os lados (azimute/distância) da planta"]
    dists, azs = res
    ll = lat_lon(textos_memorial + textos_planta)
    if not ll:
        return [], ["latitude/longitude do marco inicial ilegível"]
    c = geo.CRS[crs]
    e, nn = geo.geo_to_utm(ll[0], ll[1], c["ellipsoid"], c["zone"])
    log(f"  marco inicial: lat {ll[0]:.5f} lon {ll[1]:.5f}")

    nomes = []
    for i, (cn, _, _) in enumerate(lados):
        if cn:
            nome = cn.most_common(1)[0][0].upper()
            letra = "M" if nome[0] in "M4" else "P"
            nomes.append(f"{letra}{_dig(nome[1:])}-8")
        else:
            nomes.append(f"V{i + 1}")

    pts = [(e, nn)]
    for d, a in zip(dists, azs):
        pts.append(geo.polar(pts[-1][0], pts[-1][1], d, a))
    fech = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    soma = sum(dists)
    log(f"  poligonal: {n} lados, erro de fechamento {fech:.2f} m, perímetro {soma:.2f} m")
    tol = max(0.5, soma / 2000)
    status = "ESTIMADO"
    if fech > tol:
        avisos.append(f"poligonal não fecha (erro {fech:.2f} m) — revisar azimutes/distâncias")
        status = "REVISAR"
    if perimetro and abs(soma - perimetro) > 0.05:
        avisos.append(f"soma dos lados {soma:.2f} m difere do perímetro {perimetro:.2f} m")
        status = "REVISAR"
    linhas = []
    for i in range(n):
        p = pts[i]
        lin = Linha(nomes[i], nomes[(i + 1) % n], dists[i], azs[i], round(p[0], 2), round(p[1], 2), status)
        lin.obs.append("coordenada estimada pela poligonal a partir da lat/long do marco (±30 m)")
        linhas.append(lin)
    avisos.append("lote sem tabela de coordenadas: coordenadas ESTIMADAS a partir da planta/memorial")
    return linhas, avisos
