"""Esteira completa: PDF -> OCR -> página da tabela -> tabela -> CSV/GeoPackage."""

import os
import re
from concurrent.futures import ThreadPoolExecutor

import pymupdf

from . import cabecalho as cab
from . import geo, memorial, saida, tabela
from .ocr import render, binarize, ocr_text, ocr_words

DPI_TRIAGEM = 150
VARIANTES_CAB = [(1.0, 170), (1.5, 185), (0.6, 150)]
WORKERS = max(2, min(6, (os.cpu_count() or 4) - 1))


def _triagem(doc, log, progresso):
    """OCR rápido de todas as páginas (em paralelo) para classificar."""
    n = doc.page_count
    imgs = [render(doc[i], DPI_TRIAGEM) for i in range(n)]
    textos = [None] * n
    feitos = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futuros = {ex.submit(ocr_text, im, 3, "por"): i for i, im in enumerate(imgs)}
        for fut in futuros:
            textos[futuros[fut]] = fut.result()
            feitos += 1
            progresso(0.5 * feitos / n)
    return textos


def _ocr_paralelo(tarefas):
    """tarefas: lista de (função, args). Executa em paralelo preservando a ordem."""
    with ThreadPoolExecutor(WORKERS) as ex:
        return [f.result() for f in [ex.submit(fn, *args) for fn, args in tarefas]]


def processar_pdf(caminho, pasta_saida, crs_key=geo.CRS_PADRAO, gerar_gpkg=False,
                  log=print, progresso=lambda f: None):
    nome = os.path.basename(caminho)
    res = {"arquivo": nome, "situacao": "ERRO", "avisos": ""}
    avisos = []
    try:
        doc = pymupdf.open(caminho)
    except Exception as e:
        res["avisos"] = f"não foi possível abrir o PDF: {e}"
        return res, None
    if doc.needs_pass:
        res["avisos"] = "PDF protegido por senha"
        return res, None

    log(f"[{nome}] {doc.page_count} página(s): triagem por OCR...")
    textos = _triagem(doc, log, progresso)

    sc_tab = [cab.score_tabela(t) for t in textos]
    sc_mem = [cab.score_memorial(t) for t in textos]
    pags_tab = sorted((i for i, s in enumerate(sc_tab) if s >= 8), key=lambda i: -sc_tab[i])
    pags_mem = sorted((i for i, s in enumerate(sc_mem) if s >= 6 and i not in pags_tab),
                      key=lambda i: (-sc_mem[i], i))[:3]
    log(f"  página(s) de tabela: {[i + 1 for i in pags_tab] or 'nenhuma'}; "
        f"memorial: {[i + 1 for i in pags_mem] or 'nenhum'}")

    # ---- cabeçalho: memoriais (2 variantes) + página da tabela
    tarefas = []
    for i in pags_mem:
        r = doc[i].rect
        g = render(doc[i], 300, clip=pymupdf.Rect(0, 0, r.width, r.height * 0.45))
        tarefas += [(ocr_text, (binarize(g, b, t), 6, "por")) for b, t in VARIANTES_CAB]
    for i in pags_tab[:1]:
        tarefas.append((ocr_text, (binarize(render(doc[i], 300), 1.0, 170), 6, "por")))
    textos_cab = _ocr_paralelo(tarefas)
    k = len(VARIANTES_CAB) * len(pags_mem)
    leituras = [cab.campos_memorial(t) for t in textos_cab[:k]]
    # a página da tabela é a fonte mais limpa: vale por duas leituras
    leituras += [cab.campos_tabela(t) for t in textos_cab[k:]] * 2
    cabec = cab.consolidar(leituras, nome)
    log(f"  município: {cabec['municipio'] or '?'} | distrito: {cabec['distrito'] or '-'} | "
        f"gleba: {cabec['gleba'] or '?'} | lote: {cabec['lote'] or '?'}")
    progresso(0.6)

    # ---- tabela de coordenadas
    linhas, pag_usada = [], None
    for i in pags_tab[:3]:
        log(f"  lendo tabela da página {i + 1}...")
        ls, av = tabela.extrair(doc[i], log=log)
        ruins = sum(l.status == "REVISAR" for l in ls)
        if ls and (not linhas or ruins < sum(l.status == "REVISAR" for l in linhas)):
            linhas, pag_usada, avisos_tab = ls, i + 1, av
        if linhas and ruins == 0:
            break
    if linhas:
        avisos += avisos_tab
    progresso(0.85)

    # ---- fallback: sem tabela analítica -> poligonal da planta/memorial
    if not linhas:
        pags_planta = [i for i, t in enumerate(textos)
                       if re.search(r"AZIMUTE", cab.norm(t)) and re.search(r"CONF|LADO|DIST", cab.norm(t))
                       and i not in pags_mem]
        if pags_planta and pags_mem:
            log(f"  sem tabela de coordenadas; reconstruindo pela planta (pág. {pags_planta[0] + 1}) "
                f"e memorial (pág. {pags_mem[0] + 1})...")
            gp = render(doc[pags_planta[0]], 400)
            vp = [gp, binarize(gp, 1.0, 170), binarize(gp, 1.5, 185)]
            gm = render(doc[pags_mem[0]], 300)
            vm = [gm, binarize(gm, 1.0, 170), binarize(gm, 1.5, 185)]
            out = _ocr_paralelo([(ocr_words, (im, 6, "eng")) for im in vp] +
                                [(ocr_text, (im, 6, "por")) for im in vm])
            pw, tm = out[:3], out[3:]
            tp = [" ".join(w.text for w in ws) for ws in pw]
            linhas, av = memorial.reconstruir(pw, gp.width, 80, tm, tp, crs_key,
                                              cabec.get("perimetro"), cabec.get("area"), log=log)
            avisos += av
            pag_usada = f"{pags_planta[0] + 1} (planta)"
        else:
            avisos.append("nenhuma página com tabela de coordenadas encontrada")

    if not linhas:
        res.update(cabec)
        res["avisos"] = " | ".join(avisos)
        log(f"  ERRO: {res['avisos']}")
        return res, None

    # ---- conferências com os valores impressos no documento
    pts = [(l.e, l.n) for l in linhas if l.e == l.e]
    perim = sum(l.distancia for l in linhas if l.distancia == l.distancia)
    area = geo.area_shoelace(pts) / 1e4 if len(pts) >= 3 else float("nan")
    # O PDF pode conter outros levantamentos (ex.: memorial mais recente): basta bater com algum valor impresso
    perims = cabec.get("perimetros") or []
    areas = cabec.get("areas") or []
    if perims and not any(abs(perim - p) <= 0.05 for p in perims):
        avisos.append(f"perímetro calculado {perim:.2f} m ≠ documento {cabec['perimetro']:.2f} m")
    if areas and not any(abs(area - a) <= 0.0015 for a in areas):
        avisos.append(f"área calculada {area:.4f} ha ≠ documento {cabec['area']:.4f} ha")

    st = [l.status for l in linhas]
    if "REVISAR" in st or any("≠" in a for a in avisos):
        situacao = "REVISAR"
    elif "ESTIMADO" in st:
        situacao = "ESTIMADO"
    elif "CORRIGIDO" in st or "CALCULADO" in st:
        situacao = "OK (com correções)"
    else:
        situacao = "OK"

    base = cab.nome_base(cabec)
    os.makedirs(pasta_saida, exist_ok=True)
    csv_path = os.path.join(pasta_saida, base + ".csv")
    saida.gravar_csv(csv_path, linhas)
    lote = {"linhas": linhas, "cab": cabec, "arquivo": nome, "situacao": situacao}
    if gerar_gpkg:
        saida.gravar_gpkg(os.path.join(pasta_saida, base + ".gpkg"), [lote], crs_key)
    progresso(1.0)

    res.update(cabec)
    res.update({
        "situacao": situacao, "csv": os.path.basename(csv_path), "pagina_tabela": pag_usada,
        "vertices": len(linhas), "perimetro_calc_m": round(perim, 2),
        "perimetro_doc_m": min(perims, key=lambda p: abs(p - perim)) if perims else None,
        "area_calc_ha": round(area, 4),
        "area_doc_ha": min(areas, key=lambda a: abs(a - area)) if areas else None,
        "linhas_ok": st.count("OK"), "linhas_corrigidas": st.count("CORRIGIDO") + st.count("CALCULADO"),
        "linhas_revisar": st.count("REVISAR"), "avisos": " | ".join(avisos),
    })
    log(f"  -> {res['csv']}  [{situacao}] {len(linhas)} vértices, perímetro {perim:.2f} m, área {area:.4f} ha")
    for a in avisos:
        log(f"     aviso: {a}")
    return res, lote


def processar_lote(arquivos, pasta_saida, crs_key=geo.CRS_PADRAO, gpkg_consolidado=True,
                   gpkg_individual=False, log=print, progresso=lambda f: None):
    resultados, lotes = [], []
    n = len(arquivos)
    for k, arq in enumerate(arquivos):
        try:
            r, lote = processar_pdf(arq, pasta_saida, crs_key, gpkg_individual, log,
                                    lambda f, k=k: progresso((k + f) / n))
        except Exception as e:  # um PDF problemático não interrompe o lote
            import traceback
            log(f"  ERRO inesperado em {os.path.basename(arq)}: {e}")
            log(traceback.format_exc())
            r, lote = {"arquivo": os.path.basename(arq), "situacao": "ERRO", "avisos": str(e)}, None
        resultados.append(r)
        if lote:
            lotes.append(lote)
    os.makedirs(pasta_saida, exist_ok=True)
    saida.gravar_relatorio(os.path.join(pasta_saida, "relatorio.csv"), resultados)
    if gpkg_consolidado and lotes:
        saida.gravar_gpkg(os.path.join(pasta_saida, "lotes_consolidado.gpkg"), lotes, crs_key)
    progresso(1.0)
    return resultados
