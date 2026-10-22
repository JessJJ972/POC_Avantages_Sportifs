
"""
POC AVANTAGES SPORTIFS
Pipeline Python - version avec conservation de l'historique

Fonctionnalites :
- Lecture des donnees RH et sportives
- Conservation des activites existantes
- Simulation initiale uniquement si la base est vide
- Import de nouvelles activites depuis un CSV
- Prevention des doublons
- Calcul des avantages
- Controle des distances Google Maps (facultatif)
- Notifications Slack sportives publiques et alertes de monitoring privees (facultatif)
- Historique des executions
- Exports CSV pour Power BI

IMPORTANT :
Ce fichier utilise les fonctions d'origine conservees dans :
src/pipeline_avant_correction.py
"""

import argparse
import csv
import datetime as dt
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path


# ============================================================
# 1. CHEMINS DU PROJET
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(__file__).resolve().parent

BACKUP_FILE = SRC / "pipeline_avant_correction.py"

if not BACKUP_FILE.exists():
    raise FileNotFoundError(
        "Fichier de sauvegarde introuvable : "
        + str(BACKUP_FILE)
    )


# ============================================================
# 2. CHARGEMENT DES FONCTIONS D'ORIGINE
# ============================================================

spec = importlib.util.spec_from_file_location(
    "pipeline_original",
    BACKUP_FILE
)

original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)

SCHEMA = original.SCHEMA
DEFAULTS = original.DEFAULTS

load_employees = original.load_employees
simulate = original.simulate
validate_activity = original.validate_activity
normalize_mode = original.normalize_mode
commute_is_valid = original.commute_is_valid
google_route_distance_km = original.google_route_distance_km
notification_message = original.notification_message
send_slack = original.send_slack
build_exports = original.build_exports
from openstreetmap_routes import geocode_address, route_distance_km


# ============================================================
# 3. FONCTIONS UTILITAIRES
# ============================================================

def now_text():
    return dt.datetime.now().isoformat(timespec="microseconds")


def connect_database(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)

    for key, value in DEFAULTS.items():
        con.execute(
            """
            INSERT OR IGNORE INTO config(key, value)
            VALUES (?, ?)
            """,
            (key, value)
        )

    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_lookup
        ON activity(
            employee_id,
            start_at,
            end_at,
            sport_type,
            source
        )
        """
    )

    con.commit()
    return con


# ============================================================
# 4. CONSERVATION DES SALARIES
# ============================================================

def save_employees(con, employees):
    for employee in employees:
        con.execute(
            """
            INSERT INTO employee(
                employee_id,
                last_name,
                first_name,
                bu,
                gross_salary,
                home_address,
                commute_mode,
                declared_sport
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(employee_id)
            DO UPDATE SET
                last_name = excluded.last_name,
                first_name = excluded.first_name,
                bu = excluded.bu,
                gross_salary = excluded.gross_salary,
                home_address = excluded.home_address,
                commute_mode = excluded.commute_mode,
                declared_sport = excluded.declared_sport
            """,
            employee
        )


# ============================================================
# 5. AJOUT DES ACTIVITES SANS DOUBLONS
# ============================================================

def activity_exists(con, activity):
    result = con.execute(
        """
        SELECT activity_id
        FROM activity
        WHERE employee_id = ?
          AND start_at = ?
          AND end_at = ?
          AND sport_type = ?
          AND source = ?
        LIMIT 1
        """,
        (
            activity["employee_id"],
            activity["start_at"],
            activity["end_at"],
            activity["sport_type"],
            activity["source"]
        )
    ).fetchone()

    return result is not None


def insert_activity(con, activity):
    validate_activity(activity)

    if activity_exists(con, activity):
        return None

    cursor = con.execute(
        """
        INSERT INTO activity(
            employee_id,
            start_at,
            end_at,
            sport_type,
            distance_m,
            elapsed_s,
            comment,
            source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activity["employee_id"],
            activity["start_at"],
            activity["end_at"],
            activity["sport_type"],
            activity["distance_m"],
            activity["elapsed_s"],
            activity["comment"],
            activity["source"]
        )
    )

    return cursor.lastrowid


# ============================================================
# 6. IMPORT DE NOUVELLES ACTIVITES
# ============================================================

def import_new_activities(con, csv_path):
    csv_path = Path(csv_path)

    if not csv_path.exists():
        return []

    new_ids = []

    with csv_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        required = {
            "employee_id",
            "start_at",
            "end_at",
            "sport_type",
            "elapsed_s"
        }

        missing = required - set(reader.fieldnames or [])

        if missing:
            raise ValueError(
                "Colonnes manquantes : "
                + ", ".join(sorted(missing))
            )

        for line_number, row in enumerate(reader, start=2):
            try:
                distance_text = (
                    row.get("distance_m") or ""
                ).strip()

                activity = {
                    "employee_id": int(row["employee_id"]),
                    "start_at": row["start_at"].strip(),
                    "end_at": row["end_at"].strip(),
                    "sport_type": row["sport_type"].strip(),
                    "distance_m": (
                        int(distance_text)
                        if distance_text
                        else None
                    ),
                    "elapsed_s": int(row["elapsed_s"]),
                    "comment": (
                        row.get("comment")
                        or "Nouvelle activite"
                    ),
                    "source": (
                        row.get("source")
                        or "import_csv"
                    )
                }

                activity_id = insert_activity(
                    con,
                    activity
                )

                if activity_id is not None:
                    new_ids.append(activity_id)

            except Exception as exc:
                raise ValueError(
                    f"Erreur ligne {line_number} : {exc}"
                ) from exc

    return new_ids


# ============================================================
# 7. VERIFICATION DES DISTANCES
# ============================================================

# Coordonnees de l'entree de l'entreprise confirmees manuellement.
COMPANY_COORDINATES = (43.585927, 3.923220)


def update_commute_checks(con, employees, use_google_maps, use_openstreetmap=False):
    if use_openstreetmap:
        if use_google_maps:
            raise ValueError("Choisir Google Maps OU OpenStreetMap, pas les deux.")

        # Point GPS de l'entreprise confirme manuellement.
        # Pas de geocodage de l'adresse de l'entreprise.
    params = dict(
        con.execute("SELECT key, value FROM config")
    )

    for employee in employees:
        employee_id = employee[0]
        address = employee[5]
        mode = employee[6]

        kind = normalize_mode(mode)

        previous = con.execute(
            """
            SELECT *
            FROM commute_check
            WHERE employee_id = ?
            """,
            (employee_id,)
        ).fetchone()

        if kind == "other":
            distance = None
            status = "NON_APPLICABLE"
            source = "aucune"
            detail = "Deplacement non sportif"

        elif use_openstreetmap:
            try:
                depart_lat, depart_lon = geocode_address(address)
                arrivee_lat, arrivee_lon = COMPANY_COORDINATES

                distance = route_distance_km(
                    depart_lat,
                    depart_lon,
                    arrivee_lat,
                    arrivee_lon,
                    kind
                )

                valid = commute_is_valid(mode, distance, params)
                status = "VALIDE" if valid else "A_VERIFIER"
                source = "OpenStreetMap / Valhalla"
                detail = "Itineraire verifie"

            except Exception as exc:
                distance = None
                status = "NON_VERIFIE"
                source = "OpenStreetMap / Valhalla"
                detail = str(exc)

                con.execute(
                    """
                    INSERT INTO anomaly(category, employee_id, detail)
                    VALUES (?, ?, ?)
                    """,
                    ("distance", employee_id, str(exc))
                )
        elif use_google_maps:
            try:
                api_key = os.environ.get(
                    "GOOGLE_MAPS_API_KEY", ""
                )

                if not api_key:
                    raise ValueError(
                        "Cle Google Maps absente"
                    )

                distance = google_route_distance_km(
                    address,
                    mode,
                    api_key
                )

                valid = commute_is_valid(
                    mode,
                    distance,
                    params
                )

                status = (
                    "VALIDE"
                    if valid
                    else "A_VERIFIER"
                )

                source = "Google Routes API"
                detail = "Distance verifiee"

            except Exception as exc:
                if previous is not None:
                    distance = previous["distance_km"]
                    status = previous["status"]
                    source = previous["source"]
                    detail = previous["detail"]
                else:
                    distance = None
                    status = "NON_VERIFIE"
                    source = "aucune"
                    detail = str(exc)

                con.execute(
                    """
                    INSERT INTO anomaly(
                        category,
                        employee_id,
                        detail
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        "distance",
                        employee_id,
                        str(exc)
                    )
                )

        elif previous is not None:
            distance = previous["distance_km"]
            status = previous["status"]
            source = previous["source"]
            detail = previous["detail"]

        else:
            distance = None
            status = "NON_VERIFIE"
            source = "aucune"
            detail = "Distance non verifiee"

        con.execute(
            """
            INSERT INTO commute_check(
                employee_id,
                distance_km,
                status,
                source,
                detail
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(employee_id)
            DO UPDATE SET
                distance_km = excluded.distance_km,
                status = excluded.status,
                source = excluded.source,
                detail = excluded.detail
            """,
            (
                employee_id,
                distance,
                status,
                source,
                detail
            )
        )


# ============================================================
# 8. NOTIFICATIONS SLACK
# ============================================================

def prepare_notifications(con, new_ids):
    for activity_id in new_ids:
        activity_row = con.execute(
            """
            SELECT *
            FROM activity
            WHERE activity_id = ?
            """,
            (activity_id,)
        ).fetchone()

        if activity_row is None:
            continue

        employee_row = con.execute(
            """
            SELECT *
            FROM employee
            WHERE employee_id = ?
            """,
            (activity_row["employee_id"],)
        ).fetchone()

        if employee_row is None:
            continue

        message = notification_message(
            tuple(employee_row),
            dict(activity_row)
        )

        con.execute(
            """
            INSERT OR IGNORE INTO notification(
                activity_id,
                message,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                activity_id,
                message,
                "EN_ATTENTE",
                now_text()
            )
        )


def process_notifications(con, enable_slack):
    if not enable_slack:
        return "SLACK_DESACTIVE"

    webhook = os.environ.get(
        "SLACK_SPORT_WEBHOOK_URL", ""
    )

    if not webhook:
        return "WEBHOOK_ABSENT"

    pending = con.execute(
        """
        SELECT activity_id, message
        FROM notification
        WHERE status IN ('EN_ATTENTE', 'ERREUR_ENVOI')
        ORDER BY activity_id
        """
    ).fetchall()

    sent = 0
    errors = 0

    for item in pending:
        activity_id = item["activity_id"]

        try:
            send_slack(
                item["message"],
                webhook
            )

            con.execute(
                """
                UPDATE notification
                SET status = 'ENVOYEE'
                WHERE activity_id = ?
                """,
                (activity_id,)
            )

            con.commit()
            sent += 1

        except Exception as exc:
            con.execute(
                """
                UPDATE notification
                SET status = 'ERREUR_ENVOI'
                WHERE activity_id = ?
                """,
                (activity_id,)
            )

            con.execute(
                """
                INSERT INTO anomaly(
                    category,
                    employee_id,
                    detail
                )
                VALUES (?, ?, ?)
                """,
                (
                    "slack",
                    None,
                    f"Activite {activity_id} : {exc}"
                )
            )

            con.commit()
            errors += 1

    return f"ENVOYEES={sent};ERREURS={errors}"


# ============================================================
# 9. EXPORT DU MONITORING
# ============================================================

def export_monitoring(con, output_dir):
    """Exporte toutes les executions avec une duree precise en secondes."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = con.execute(
        """
        SELECT run_id, started_at, ended_at, status,
               employees, activities, anomalies, error_message
        FROM pipeline_run
        ORDER BY run_id
        """
    ).fetchall()

    columns = [
        "run_id", "started_at", "ended_at", "status",
        "employees", "activities", "anomalies",
        "error_message", "duration_seconds"
    ]

    with (output_dir / "monitoring.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.writer(file)
        writer.writerow(columns)

        for row in rows:
            duration = None
            if row["started_at"] and row["ended_at"]:
                start = dt.datetime.fromisoformat(row["started_at"])
                end = dt.datetime.fromisoformat(row["ended_at"])
                duration = round((end - start).total_seconds(), 6)

            writer.writerow([*tuple(row), duration])


# ============================================================
# 10. EXECUTION DU PIPELINE
# ============================================================

def execute(args):
    db_path = Path(args.db)
    output_dir = Path(args.output)

    # Verification avant toute ecriture dans SQLite ou les exports.
    if args.openstreetmap:
        if args.google_maps:
            raise ValueError(
                "Choisir Google Maps OU OpenStreetMap, pas les deux."
            )

        # Coordonnees de l'entreprise disponibles localement.
        # Aucun appel au geocodeur avant ouverture de SQLite.

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    con = connect_database(db_path)

    cursor = con.execute(
        """
        INSERT INTO pipeline_run(
            started_at,
            status
        )
        VALUES (?, 'RUNNING')
        """,
        (now_text(),)
    )

    run_id = cursor.lastrowid
    con.commit()

    try:
        # Parametres
        if args.prime_rate is not None:
            if not 0 <= args.prime_rate <= 1:
                raise ValueError(
                    "Taux de prime invalide"
                )

            con.execute(
                """
                UPDATE config
                SET value = ?
                WHERE key = 'prime_rate'
                """,
                (args.prime_rate,)
            )

        if args.threshold is not None:
            if args.threshold < 1:
                raise ValueError(
                    "Seuil invalide"
                )

            con.execute(
                """
                UPDATE config
                SET value = ?
                WHERE key = 'wellbeing_activity_threshold'
                """,
                (args.threshold,)
            )

        # Import RH
        employees, anomalies = load_employees(
            args.rh,
            args.sports
        )

        if not employees:
            raise ValueError(
                "Aucun salarie importe"
            )

        save_employees(
            con,
            employees
        )

        for anomaly in anomalies:
            con.execute(
                """
                INSERT INTO anomaly(
                    category,
                    employee_id,
                    detail
                )
                VALUES (?, ?, ?)
                """,
                anomaly
            )

        # Distances
        update_commute_checks(
            con,
            employees,
            args.google_maps,
            args.openstreetmap
        )

        # Conservation de l'historique
        existing_count = con.execute(
            "SELECT COUNT(*) FROM activity"
        ).fetchone()[0]

        if existing_count == 0:
            simulated = simulate(
                employees,
                seed=args.seed
            )

            for activity in simulated:
                insert_activity(
                    con,
                    activity
                )

            print(
                "Historique simule initialise."
            )

        else:
            print(
                f"Historique conserve : "
                f"{existing_count} activites."
            )

        # Ajout de nouvelles activites
        new_ids = import_new_activities(
            con,
            args.new_activities
        )

        prepare_notifications(
            con,
            new_ids
        )

        con.commit()

        # Slack
        slack_status = process_notifications(
            con,
            args.slack
        )

        # Volumes
        employees_count = con.execute(
            "SELECT COUNT(*) FROM employee"
        ).fetchone()[0]

        activities_count = con.execute(
            "SELECT COUNT(*) FROM activity"
        ).fetchone()[0]

        anomalies_count = con.execute(
            "SELECT COUNT(*) FROM anomaly"
        ).fetchone()[0]

        # Exports Power BI
        build_exports(
            con,
            output_dir
        )

        # Succes
        con.execute(
            """
            UPDATE pipeline_run
            SET
                ended_at = ?,
                status = 'SUCCESS',
                employees = ?,
                activities = ?,
                anomalies = ?
            WHERE run_id = ?
            """,
            (
                now_text(),
                employees_count,
                activities_count,
                anomalies_count,
                run_id
            )
        )

        con.commit()

        export_monitoring(
            con,
            output_dir
        )

        print(
            json.dumps(
                {
                    "status": "SUCCESS",
                    "employees": employees_count,
                    "activities": activities_count,
                    "new_activities": len(new_ids),
                    "anomalies": anomalies_count,
                    "db": str(db_path),
                    "exports": str(output_dir),
                    "google_maps": args.google_maps,
                    "slack": slack_status
                },
                ensure_ascii=False,
                indent=2
            )
        )

    except Exception as exc:
        con.rollback()

        con.execute(
            """
            UPDATE pipeline_run
            SET
                ended_at = ?,
                status = 'FAILED',
                error_message = ?
            WHERE run_id = ?
            """,
            (
                now_text(),
                str(exc),
                run_id
            )
        )

        con.commit()

        try:
            export_monitoring(
                con,
                output_dir
            )
        except Exception as export_exc:
            print(
                "ERREUR EXPORT MONITORING : " + str(export_exc),
                file=sys.stderr
            )

        if args.slack:
            webhook = os.environ.get("SLACK_MONITORING_WEBHOOK_URL", "")
            if webhook:
                try:
                    send_slack(
                        "ALERTE POC AVANTAGES SPORTIFS\n"
                        + "Pipeline en echec\n"
                        + "Execution : " + str(run_id) + "\n"
                        + "Erreur : " + str(exc),
                        webhook
                    )
                    print("ALERTE_SLACK_ENVOYEE")
                except Exception as slack_exc:
                    print(
                        "ERREUR ALERTE SLACK : " + str(slack_exc),
                        file=sys.stderr
                    )

        print(
            "ERREUR : " + str(exc),
            file=sys.stderr
        )

        raise

    finally:
        con.close()


# ============================================================
# 11. PARAMETRES DE LANCEMENT
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="POC Avantages Sportifs"
    )

    parser.add_argument(
        "--rh",
        default=str(
            ROOT / "data/input/rh.xlsx"
        )
    )

    parser.add_argument(
        "--sports",
        default=str(
            ROOT / "data/input/sports.xlsx"
        )
    )

    parser.add_argument(
        "--db",
        default=str(
            ROOT / "data/poc_sport.sqlite"
        )
    )

    parser.add_argument(
        "--output",
        default=str(
            ROOT / "data/output"
        )
    )

    parser.add_argument(
        "--new-activities",
        default=str(
            ROOT / "data/input/nouvelles_activites.csv"
        )
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42
    )

    parser.add_argument(
        "--prime-rate",
        type=float,
        default=None
    )

    parser.add_argument(
        "--threshold",
        type=int,
        default=None
    )

    parser.add_argument(
        "--google-maps",
        action="store_true"
    )

    parser.add_argument("--openstreetmap", action="store_true", help="Activer OpenStreetMap")
    parser.add_argument(
        "--slack",
        action="store_true"
    )

    args = parser.parse_args()

    execute(args)


# ============================================================
# 12. DEMARRAGE
# ============================================================

if __name__ == "__main__":
    main()
