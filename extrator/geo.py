"""Geometria plana (UTM), conversão geográfica -> UTM e sistemas de referência."""

import math

# Sistemas de referência oferecidos. Todos UTM fuso 24 Sul (Sergipe).
# ellipsoid: (a, 1/f) usado na conversão lat/long -> UTM do fallback.
CRS = {
    "SAD69 / UTM 24S (EPSG:29194)": {
        "epsg": 29194, "ellipsoid": (6378160.0, 298.25), "zone": 24,
        "name": "SAD69 / UTM zone 24S",
    },
    "SIRGAS 2000 / UTM 24S (EPSG:31984)": {
        "epsg": 31984, "ellipsoid": (6378137.0, 298.257222101), "zone": 24,
        "name": "SIRGAS 2000 / UTM zone 24S",
    },
    "Córrego Alegre / UTM 24S (EPSG:22524)": {
        "epsg": 22524, "ellipsoid": (6378388.0, 297.0), "zone": 24,
        "name": "Corrego Alegre 1970-72 / UTM zone 24S",
    },
}
CRS_PADRAO = "SAD69 / UTM 24S (EPSG:29194)"


def dist_az(e1, n1, e2, n2):
    """Distância (m) e azimute de quadrícula (graus decimais, 0-360) de P1 para P2."""
    de, dn = e2 - e1, n2 - n1
    az = math.degrees(math.atan2(de, dn)) % 360.0
    return math.hypot(de, dn), az


def polar(e, n, d, az):
    r = math.radians(az)
    return e + d * math.sin(r), n + d * math.cos(r)


def az_diff(a, b):
    """Diferença angular absoluta em segundos de arco."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d) * 3600.0


def area_shoelace(pts):
    s = 0.0
    for (e1, n1), (e2, n2) in zip(pts, pts[1:] + pts[:1]):
        s += e1 * n2 - e2 * n1
    return abs(s) / 2.0


def dms_to_deg(g, m, s):
    return g + m / 60.0 + s / 3600.0


def deg_to_dms(az):
    total = round(az * 3600)
    g, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return int(g) % 360, int(m), int(s)


def fmt_dms(az):
    g, m, s = deg_to_dms(az)
    return f"{g}°{m:02d}'{s:02d}\""


def geo_to_utm(lat, lon, ellipsoid, zone):
    """Projeção transversa de Mercator (série de Krüger), hemisfério sul. lat/lon em graus."""
    a, invf = ellipsoid
    f = 1 / invf
    k0 = 0.9996
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    alpha = [n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16,
             13 * n ** 2 / 48 - 3 * n ** 3 / 5,
             61 * n ** 3 / 240]
    lon0 = math.radians(zone * 6 - 183)
    phi, lam = math.radians(lat), math.radians(lon) - lon0
    e = math.sqrt(f * (2 - f))
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi_p = math.atan2(t, math.cos(lam))
    eta_p = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    xi, eta = xi_p, eta_p
    for j, al in enumerate(alpha, start=1):
        xi += al * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta += al * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)
    E = 500000 + k0 * A * eta
    N = k0 * A * xi
    if lat < 0:
        N += 10000000
    return E, N
