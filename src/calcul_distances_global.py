from pathlib import Path
import sqlite3
import sys
import re
import time
import argparse
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openstreetmap_routes import geocode_address, route_distance_km
from pipeline import normalize_mode, commute_is_valid

BASE = Path("data/calcul_distances_global/distances.sqlite")
ENTREPRISE = (43.585927, 3.923220)
SOURCE = "OpenStreetMap / Valhalla"


def main():
    parser = argparse.ArgumentParser(
        description="Calcul progressif des distances du POC"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Nombre maximal de trajets a traiter"
    )

    args = parser.parse_args()

    if args.limit < 1:
        raise ValueError("La limite doit etre positive.")

    if not BASE.exists():
        raise FileNotFoundError(
            f"Base introuvable : {BASE}"
        )

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
                c.status,
                c.source,
                c.detail
            FROM employee e
            JOIN commute_check c
              ON c.employee_id = e.employee_id
            WHERE c.status = 'NON_VERIFIE'
            ORDER BY e.employee_id
        """).fetchall()

        calcules = 0
        refuses = 0
        ignores = 0
        deja_traites = 0
        interrompu = False

        for ligne in lignes:

            if calcules + refuses >= args.limit:
                break

            identifiant = ligne["employee_id"]
            adresse = (ligne["home_address"] or "").strip()
            mode = ligne["commute_mode"]

            profil = normalize_mode(mode)

            # Ne pas retenter automatiquement les echecs
            # deja enregistres par ce calculateur.
            if (
                ligne["source"] == SOURCE
                and ligne["detail"]
                and str(ligne["detail"]).startswith(
                    "ECHEC_CALCUL_GLOBAL:"
                )
            ):
                deja_traites += 1
                continue

            if profil not in ("walk", "bike"):
                ignores += 1
                continue

            # Le geocodeur actuel exige un numero
            # de rue au debut de l'adresse.
            if not re.match(
                r"^\d+[a-zA-Z]?\b",
                adresse
            ):
                ignores += 1
                continue

            print(
                f"\nSalarie {identifiant} | Mode : {profil}",
                flush=True
            )

            try:
                lat, lon = geocode_address(adresse)

                distance = route_distance_km(
                    lat,
                    lon,
                    ENTREPRISE[0],
                    ENTREPRISE[1],
                    profil
                )

                valide = commute_is_valid(
                    mode,
                    distance,
                    params
                )

                statut = (
                    "VALIDE"
                    if valide
                    else "A_VERIFIER"
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
                    "Itineraire reel calcule",
                    identifiant
                ))

                con.commit()

                calcules += 1

                print(
                    f"  {distance:.3f} km | "
                    f"{statut} | ENREGISTRE",
                    flush=True
                )

            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                ConnectionError
            ) as erreur:

                print(
                    "  Service indisponible :",
                    type(erreur).__name__,
                    str(erreur),
                    flush=True
                )

                print(
                    "  Traitement interrompu."
                )

                interrompu = True
                break

            except ValueError as erreur:

                refuses += 1

                print(
                    "  NON_VERIFIE :",
                    str(erreur),
                    flush=True
                )

                con.execute("""
                    UPDATE commute_check
                    SET
                        distance_km = NULL,
                        status = 'NON_VERIFIE',
                        source = ?,
                        detail = ?
                    WHERE employee_id = ?
                      AND status = 'NON_VERIFIE'
                """, (
                    SOURCE,
                    "ECHEC_CALCUL_GLOBAL: " + str(erreur),
                    identifiant
                ))

                con.commit()

            except Exception as erreur:

                print(
                    "  Erreur inattendue :",
                    type(erreur).__name__,
                    str(erreur),
                    flush=True
                )

                interrompu = True
                break

            # Eviter les appels rapproches.
            time.sleep(2)

        print("\n=== BILAN DE CETTE EXECUTION ===")

        print("Distances enregistrees :", calcules)
        print("Adresses refusees :", refuses)
        print("Adresses ignorees :", ignores)
        print("Echecs deja traites :", deja_traites)
        print(
            "Traitement interrompu :",
            "OUI" if interrompu else "NON"
        )

        print("\n=== STATUTS DANS LA BASE ===")

        for statut, nombre in con.execute("""
            SELECT status, COUNT(*)
            FROM commute_check
            GROUP BY status
            ORDER BY status
        """):
            print(f"{statut} : {nombre}")

        print("\nBase utilisee :", BASE)
        print("Base du jury non modifiee.")
        print("Slack non utilise.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
