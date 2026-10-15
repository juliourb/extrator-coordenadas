"""Extrator de Coordenadas do Italo — interface gráfica.

Seleciona PDFs (ou uma pasta), localiza a página "Descrição Analítica do Lote",
extrai a tabela de coordenadas por OCR e grava, para cada PDF:
  MUNICIPIO_DISTRITO_GLEBA_LOTE_n.csv  (separador ";", decimal ",")
além de relatorio.csv e lotes_consolidado.gpkg (camadas "poligono" e "vertices")
com todos os lotes. Opcionalmente, um .gpkg individual por PDF.

Uso sem interface: app.py --cli <pdf ou pasta> [pasta_saida]
"""

import os
import sys
import glob
import threading
import traceback


TITULO = "Extrator de Coordenadas do Italo"


def recurso(*partes):
    """Caminho de um arquivo empacotado (funciona no exe do PyInstaller e no código-fonte)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *partes)


def listar_pdfs(entrada: str):
    arquivos = []
    for parte in entrada.split(";"):
        parte = parte.strip()
        if not parte:
            continue
        if os.path.isdir(parte):
            arquivos += sorted(glob.glob(os.path.join(parte, "*.pdf")) + glob.glob(os.path.join(parte, "*.PDF")))
        elif parte.lower().endswith(".pdf") and os.path.isfile(parte):
            arquivos.append(parte)
    return list(dict.fromkeys(os.path.normpath(a) for a in arquivos))


def pasta_padrao(entrada: str):
    primeiro = entrada.split(";")[0].strip()
    base = primeiro if os.path.isdir(primeiro) else os.path.dirname(primeiro)
    return os.path.join(base, "coordenadas_extraidas") if base else ""


def cli(args):
    from extrator.pipeline import processar_lote
    arquivos = listar_pdfs(args[0])
    saida = args[1] if len(args) > 1 else pasta_padrao(args[0])
    processar_lote(arquivos, saida)
    print(f"Resultados em: {saida}")


def gui():
    import FreeSimpleGUI as sg
    from extrator import geo
    from extrator.pipeline import processar_lote

    # Faz o Windows agrupar a janela com o ícone do app (e não o do Python) na barra de tarefas
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("italo.extrator.coordenadas")
    except Exception:
        pass

    sg.theme("SystemDefault")
    controles = [
        [sg.Text(TITULO, font=("Segoe UI", 13, "bold"))],
        [sg.Text("Lê a tabela \"Descrição Analítica do Lote\" dos PDFs escaneados.", font=("Segoe UI", 9))],
        [sg.Text("PDFs de entrada:", size=(16, 1)),
         sg.Input(key="entrada", size=(58, 1), enable_events=True),
         sg.FilesBrowse("Arquivos...", file_types=(("PDF", "*.pdf"),), target="entrada"),
         sg.FolderBrowse("Pasta...", target="entrada")],
        [sg.Text("Pasta de saída:", size=(16, 1)), sg.Input(key="saida", size=(58, 1)),
         sg.FolderBrowse("Escolher...", target="saida")],
        [sg.Text("Sistema de referência:", size=(16, 1)),
         sg.Combo(list(geo.CRS), default_value=geo.CRS_PADRAO, key="crs", readonly=True, size=(40, 1))],
        [sg.Checkbox("GeoPackage consolidado (todos os lotes)", default=True, key="gpkg_cons"),
         sg.Checkbox("GeoPackages individuais (um por PDF)", default=False, key="gpkg_ind")],
        [sg.Button("Processar", key="processar", size=(16, 1), button_color=("white", "#2b6cb0")),
         sg.Button("Abrir pasta de saída", key="abrir", disabled=True),
         sg.Push(), sg.Text("", key="status")],
    ]
    retrato = [[sg.Image(recurso("assets", "italo.png"), pad=(10, 0))]]
    layout = [
        [sg.Column(controles, vertical_alignment="top"), sg.Push(),
         sg.Column(retrato, vertical_alignment="top")],
        [sg.ProgressBar(1000, orientation="h", size=(66, 16), key="prog", expand_x=True)],
        [sg.Multiline("", key="log", size=(110, 20), autoscroll=True, disabled=True,
                      font=("Consolas", 9), expand_x=True)],
        [sg.Text("Situação: OK = conferido pela geometria | OK (com correções) = valores ilegíveis "
                 "recalculados | REVISAR / ESTIMADO = conferir manualmente", font=("Segoe UI", 8))],
    ]
    icone = recurso("assets", "icone.ico")
    win = sg.Window(TITULO, layout, finalize=True, icon=icone if os.path.exists(icone) else None)

    def log(msg):
        win.write_event_value("-LOG-", msg)

    def progresso(f):
        win.write_event_value("-PROG-", f)

    def trabalho(arquivos, saida, crs, cons, ind):
        try:
            res = processar_lote(arquivos, saida, crs, cons, ind, log=log, progresso=progresso)
            win.write_event_value("-FIM-", res)
        except Exception:
            win.write_event_value("-ERRO-", traceback.format_exc())

    rodando = False
    while True:
        ev, val = win.read()
        if ev == sg.WINDOW_CLOSED:
            if rodando and sg.popup_yes_no("O processamento ainda está em andamento. Sair mesmo assim?") != "Yes":
                continue
            break
        if ev == "entrada" and not val["saida"]:
            win["saida"].update(pasta_padrao(val["entrada"]))
        elif ev == "processar":
            arquivos = listar_pdfs(val["entrada"])
            if not arquivos:
                sg.popup_error("Nenhum PDF encontrado. Selecione arquivos ou uma pasta.")
                continue
            saida = val["saida"] or pasta_padrao(val["entrada"])
            win["saida"].update(saida)
            win["log"].update("")
            win["prog"].update(0)
            win["processar"].update(disabled=True)
            win["status"].update(f"Processando {len(arquivos)} PDF(s)...")
            rodando = True
            threading.Thread(target=trabalho,
                             args=(arquivos, saida, val["crs"], val["gpkg_cons"], val["gpkg_ind"]),
                             daemon=True).start()
        elif ev == "-LOG-":
            win["log"].print(val[ev])
        elif ev == "-PROG-":
            win["prog"].update(int(val[ev] * 1000))
        elif ev == "-FIM-":
            rodando = False
            res = val[ev]
            ok = sum(r["situacao"].startswith("OK") for r in res)
            rev = len(res) - ok
            win["status"].update(f"Concluído: {ok} OK, {rev} para revisar/erro")
            win["log"].print(f"\nConcluído. {ok} OK, {rev} para revisar/erro. Veja relatorio.csv.")
            win["processar"].update(disabled=False)
            win["abrir"].update(disabled=False)
        elif ev == "-ERRO-":
            rodando = False
            win["log"].print(val[ev])
            win["status"].update("Erro — veja o log")
            win["processar"].update(disabled=False)
        elif ev == "abrir":
            pasta = val["saida"]
            if pasta and os.path.isdir(pasta):
                os.startfile(pasta)
    win.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        cli(sys.argv[2:])
    else:
        gui()
