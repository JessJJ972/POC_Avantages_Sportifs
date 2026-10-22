import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import normalize_mode, commute_is_valid
from openstreetmap_routes import route_distance_km

BASE = Path("data/calcul_distances_global/distances.sqlite")
LAT_ENTREPRISE = 43.585927
LON_ENTREPRISE = 3.923220

SOURCE = "IGN / BAN + OpenStreetMap / Valhalla"
MARQUEUR = "ECHEC_IGN_GLOBAL:"


def normaliser(texte):
    texte = unicodedata.normalize("NFKD", str(texte or ""))
    texte = "".join(
        c for c in texte
        if not unicodedata.combining(c)
    )
    texte = texte.lower()
    texte = re.sub(r"[^a-z0-9]+", " ", texte)
    return " ".join(texte.split())


def normaliser_rue(texte):
    mots = normaliser(texte).split()

    abreviations = {
        "av": "avenue",
        "bd": "boulevard",
        "imp": "impasse",
        "rte": "route",
        "pl": "place",
        "che": "chemin",
    }

    return " ".join(abreviations.get(m, m) for m in mots)


def geocoder_ign(adresse):
    numero = re.match(r"^\s*(\d+[a-zA-Z]?)\b", adresse)
    cp = re.search(r"\b(\d{5})\b", adresse)

    if not numero or not cp:
        raise ValueError("Numero de rue ou code postal absent")

    parties = adresse.split(",")

    if len(parties) < 2:
        raise ValueError("Adresse incomplete")

    numero_attendu = normaliser(numero.group(1))
    cp_attendu = cp.group(1)

    rue_attendue = re.sub(
        r"^\s*\d+[a-zA-Z]?\s*",
        "",
        parties[0]
    )
    rue_attendue = normaliser_rue(rue_attendue)

    parametres = urllib.parse.urlencode({
        "q": adresse,
        "limit": 5,
        "autocomplete": 0,
    })

    url = (
        "https://data.geopf.fr/geocodage/search?"
        + parametres
    )

    requete = urllib.request.Request(
        url,
        headers={
            "User-Agent": "POC-Avantages-Sportifs-Demo/1.0",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(requete, timeout=25) as reponse:
        donnees = json.load(reponse)

    for resultat in donnees.get("features", []):
        propr = resultat.get("properties", {})

        if propr.get("type") != "housenumber":
            continue

        if normaliser(propr.get("housenumber")) != numero_attendu:
            continue

        if str(propr.get("postcode")) != cp_attendu:
            continue

        score = float(propr.get("score") or 0)

        if score < 0.90:
            continue

        rue_ign = normaliser_rue(propr.get("street"))

        if rue_ign != rue_attendue:
            continue

        coord = resultat.get(
            "geometry", {}
        ).get("coordinates", [])

        if len(coord) != 2:
            continue

        longitude, latitude = coord

        return latitude, longitude, propr.get("label"), score

    raise ValueError(
        "Adresse exacte non confirmee par IGN"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    if args.limit < 1:
        raise ValueError("Limite invalide")

    if not BASE.exists():
        raise FileNotFoundError(BASE)

    con = sqlite3.connect(BASE)
    con.row_factory = sqlite3.Row

    try:
        params = dict(
            con.execute("SELECT key, value FROM config")
        )

        lignes = con.execute("""
            SELECT
                e.employee_id,
                e.home_address,
                e.commute_mode,
                c.detail
            FROM employee e
            JOIN commute_check c
                ON e.employee_id = c.employee_id
            WHERE c.status = 'NON_VERIFIE'
            ORDER BY e.employee_id
        """).fetchall()

        reussites = 0
        non_fiabilisees = 0

        for ligne in lignes:
            if reussites + non_fiabilisees >= args.limit:
                break

            identifiant = ligne["employee_id"]
            adresse = (ligne["home_address"] or "").strip()
            mode = ligne["commute_mode"]
            detail = ligne["detail"] or ""

            if detail.startswith(MARQUEUR):
                continue

            profil = normalize_mode(mode)

            if profil not in ("bike", "walk"):
                continue

            print(
                f"\nSalarie {identifiant} - {profil}",
                flush=True
            )

            try:
                latitude, longitude, libelle, score = geocoder_ign(
                    adresse
                )

                print("Adresse IGN :", libelle, flush=True)

                time.sleep(1.5)

                distance = route_distance_km(
                    latitude,
                    longitude,
                    LAT_ENTREPRISE,
                    LON_ENTREPRISE,
                    profil,
                )

                if distance is None or distance <= 0:
                    raise RuntimeError(
                        "Distance Valhalla indisponible"
                    )

                valide = commute_is_valid(
                    mode,
                    distance,
                    params,
                )

                statut = (
                    "VALIDE" if valide else "A_VERIFIER"
                )

                con.execute("""
                    UPDATE commute_check
                    SET
                        distance_km = ?,
                        status = ?,
                        source = ?,
                        detail = ?
                    WHERE employee_id = ?
                      AND status = 'NON_VERIFIE'
                """, (
                    distance,
                    statut,
                    SOURCE,
                    f"Adresse IGN : {libelle}; "
                    f"score={score:.3f}; itineraire reel",
                    identifiant,
                ))

                con.commit()
                reussites += 1

                print(
                    f"Distance : {distance:.3f} km - {statut}",
                    flush=True
                )

            except ValueError as erreur:
                con.execute("""
                    UPDATE commute_check
                    SET
                        status = 'NON_VERIFIE',
                        distance_km = NULL,
                        source = ?,
                        detail = ?
                    WHERE employee_id = ?
                      AND status = 'NON_VERIFIE'
                """, (
                    SOURCE,
                    MARQUEUR + " " + str(erreur),
                    identifiant,
                ))

                con.commit()
                non_fiabilisees += 1

                print(
                    "Distance non fiabilisee :",
                    erreur,
                    flush=True
                )

            except Exception as erreur:
                print(
                    "Erreur technique :",
                    type(erreur).__name__,
                    str(erreur),
                    flush=True
                )
                print(
                    "Arret : ce trajet pourra etre retente."
                )
                break

            time.sleep(2)

        print("\n=== BILAN ===")
        print("Distances calculees :", reussites)
        print("Adresses non fiabilisees :", non_fiabilisees)

        for statut, nombre in con.execute("""
            SELECT status, COUNT(*)
            FROM commute_check
            GROUP BY status
            ORDER BY status
        """):
            print(statut, ":", nombre)

        print("\nBase du jury non modifiee.")

    finally:
        con.close()


if __name__ == "__main__":
    main()