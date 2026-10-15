"""Gravação dos resultados: CSV (padrão Excel BR) e GeoPackage (sqlite, sem GDAL)."""

import os
import csv
import json
import math
import sqlite3
import struct

from . import geo

_WKT = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wkt.json"),
                      encoding="utf-8"))

COLUNAS_CSV = ["ordem", "ponto_a", "ponto_b", "distancia_m", "azimute", "azimute_graus",
               "E", "N", "status", "observacao"]


def _br(v, casas):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return f"{v:.{casas}f}".replace(".", ",")


def gravar_csv(caminho, linhas):
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLUNAS_CSV)
        for i, l in enumerate(linhas, start=1):
            az_ok = l.azimute == l.azimute
            w.writerow([i, l.ponto_a, l.ponto_b, _br(l.distancia, 2),
                        geo.fmt_dms(l.azimute) if az_ok else "", _br(l.azimute, 6) if az_ok else "",
                        _br(l.e, 2), _br(l.n, 2), l.status, "; ".join(l.obs)])


def gravar_relatorio(caminho, resultados):
    cols = ["arquivo", "situacao", "csv", "municipio", "distrito", "gleba", "lote",
            "pagina_tabela", "vertices", "perimetro_calc_m", "perimetro_doc_m",
            "area_calc_ha", "area_doc_ha", "linhas_ok", "linhas_corrigidas", "linhas_revisar", "avisos"]
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for r in resultados:
            w.writerow([_br(r.get(c), 4 if c.startswith("area") else 2) if isinstance(r.get(c), float)
                        else r.get(c, "") for c in cols])


# ---------------------------------------------------------------- GeoPackage

def _gpkg_blob(srs_id, wkb, env):
    # Cabeçalho GPKG: "GP", versão 0, flags (little endian + envelope xy), srs_id, envelope
    return b"GP" + bytes([0, 0b00000011]) + struct.pack("<i4d", srs_id, env[0], env[1], env[2], env[3]) + wkb


def _wkb_ponto(e, n):
    return struct.pack("<BIdd", 1, 1, e, n)


def _wkb_poligono(pts):
    anel = list(pts) + [pts[0]]
    b = struct.pack("<BII", 1, 3, 1) + struct.pack("<I", len(anel))
    for e, n in anel:
        b += struct.pack("<dd", e, n)
    return b


def _criar_gpkg(caminho, epsg, nome_crs):
    if os.path.exists(caminho):
        os.remove(caminho)
    con = sqlite3.connect(caminho)
    con.execute("PRAGMA application_id = 1196444487")  # 'GPKG'
    con.execute("PRAGMA user_version = 10200")
    con.executescript("""
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY,
            organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL, description TEXT);
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, data_type TEXT NOT NULL,
            identifier TEXT UNIQUE, description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER,
            CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
        CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL, z TINYINT NOT NULL,
            m TINYINT NOT NULL, CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));
    """)
    con.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)", [
        ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", None),
        ("Undefined geographic SRS", 0, "NONE", 0, "undefined", None),
        ("WGS 84 geodetic", 4326, "EPSG", 4326,
         'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
         'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]', None),
        (nome_crs, epsg, "EPSG", epsg, _WKT[str(epsg)], None),
    ])
    con.executescript("""
        CREATE TABLE poligono (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom POLYGON,
            municipio TEXT, distrito TEXT, gleba TEXT, lote TEXT, area_ha REAL, perimetro_m REAL,
            vertices INTEGER, situacao TEXT, arquivo_origem TEXT);
        CREATE TABLE vertices (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom POINT,
            nome TEXT, ordem INTEGER, E REAL, N REAL, lote TEXT, status TEXT, arquivo_origem TEXT);
    """)
    for t, tipo in (("poligono", "POLYGON"), ("vertices", "POINT")):
        con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id) "
                    "VALUES (?, 'features', ?, ?)", (t, t, epsg))
        con.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)", (t, tipo, epsg))
    return con


def gravar_gpkg(caminho, lotes, crs_key):
    """lotes: lista de dicts com 'linhas', 'cab', 'arquivo', 'situacao'."""
    c = geo.CRS[crs_key]
    epsg = c["epsg"]
    con = _criar_gpkg(caminho, epsg, c["name"])
    env_total = [math.inf, -math.inf, math.inf, -math.inf]
    for lote in lotes:
        pts = [(l.e, l.n) for l in lote["linhas"] if l.e == l.e and l.n == l.n]
        if len(pts) < 3:
            continue
        es, ns = [p[0] for p in pts], [p[1] for p in pts]
        env = (min(es), max(es), min(ns), max(ns))
        env_total = [min(env_total[0], env[0]), max(env_total[1], env[1]),
                     min(env_total[2], env[2]), max(env_total[3], env[3])]
        cab = lote["cab"]
        con.execute(
            "INSERT INTO poligono (geom, municipio, distrito, gleba, lote, area_ha, perimetro_m, "
            "vertices, situacao, arquivo_origem) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_gpkg_blob(epsg, _wkb_poligono(pts), env), cab.get("municipio"), cab.get("distrito"),
             cab.get("gleba"), cab.get("lote"), round(geo.area_shoelace(pts) / 1e4, 4),
             round(sum(l.distancia for l in lote["linhas"] if l.distancia == l.distancia), 2),
             len(pts), lote["situacao"], lote["arquivo"]))
        for i, l in enumerate(lote["linhas"], start=1):
            if l.e != l.e:
                continue
            con.execute(
                "INSERT INTO vertices (geom, nome, ordem, E, N, lote, status, arquivo_origem) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (_gpkg_blob(epsg, _wkb_ponto(l.e, l.n), (l.e, l.e, l.n, l.n)), l.ponto_a, i,
                 l.e, l.n, cab.get("lote"), l.status, lote["arquivo"]))
    if env_total[0] != math.inf:
        con.execute("UPDATE gpkg_contents SET min_x=?, max_x=?, min_y=?, max_y=?", env_total)
    con.commit()
    con.close()
