import imp
import os
import json
import logging
import boto3
import psycopg2
from psycopg2.extras import execute_values
from prometheus_client import Counter, Histogram, start_http_server
from dotenv import load_dotenv

# Prometheus metrics
files_processed = Counter("f1_files_processed_total", "Number of raw files processed")
processing_time = Histogram("f1_processing_seconds", "Time taken to process a file")

# AWS/DB Config
load_dotenv()
S3_BUCKET = os.environ["F1_S3_BUCKET"]
DB_HOST = os.environ["DB_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASS"]
DB_PORT = os.environ.get("DB_PORT", 5432)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# AWS/DB helper functions
def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )

def list_new_objects(source_prefix):
    """List objects in S3 under raw/{date}/{source}/"""
    s3 = boto3.client("s3")
    resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="raw/")
    for obj in resp.get("Contents", []):
        if source_prefix in obj["Key"]:
            yield obj["Key"]

def fetch_object(key):
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
    return resp["Body"].read().decode("utf-8")

# ---------------------------
# Process Ergast/Jolpica JSON
# ---------------------------
def process_ergast(key):
    logging.info(f"Processing Ergast data from {key}")
    raw = fetch_object(key)
    data = json.loads(raw)

    race_data = data["MRData"]["RaceTable"]["Races"][0]

    season = int(race_data["season"])
    round_ = int(race_data["round"])
    race_name = race_data["raceName"]
    circuit_name = race_data["Circuit"]["circuitName"]
    date = race_data["date"]
    location = race_data["Circuit"]["Location"]["locality"]
    country = race_data["Circuit"]["Location"]["country"]

    with get_db_conn() as conn, conn.cursor() as cur:
        # Insert race
        cur.execute(
            """
            INSERT INTO races (season, round, race_name, circuit_name, date, location, country)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (season, round) DO UPDATE SET race_name=EXCLUDED.race_name
            RETURNING id
            """,
            (season, round_, race_name, circuit_name, date, location, country),
        )
        race_id = cur.fetchone()[0]

        driver_code_map = {}

        # Insert drivers + teams
        if "Results" not in race_data:
            logging.warning(f"No Results found for race: {race_data.get('raceName', 'unknown')}, skipping.")
            return None, {}

        for res in race_data["Results"]:
            d = res["Driver"]
            t = res["Constructor"]

            # Teams
            cur.execute(
                """
                INSERT INTO teams (team_ref, name, nationality)
                VALUES (%s,%s,%s)
                ON CONFLICT (team_ref) DO NOTHING
                RETURNING id
                """,
                (t["constructorId"], t["name"], t["nationality"]),
            )
            team_id = cur.fetchone()[0] if cur.rowcount > 0 else None

            # Drivers
            cur.execute(
                """
                INSERT INTO drivers (driver_ref, given_name, family_name, code, nationality, date_of_birth, team_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (driver_ref) DO UPDATE SET team_id=EXCLUDED.team_id
                RETURNING id, code
                """,
                (
                    d["driverId"],
                    d["givenName"],
                    d["familyName"],
                    d.get("code"),
                    d["nationality"],
                    d["dateOfBirth"],
                    team_id,
                ),
            )
            driver_id, driver_code = cur.fetchone()
            if driver_code:
                driver_code_map[driver_code] = driver_id

        conn.commit()

    files_processed.inc()
    return race_id, driver_code_map

# ---------------------------
# Process FastF1 JSON (laps)
# ---------------------------
@processing_time.time()
def process_fastf1(key, race_id, driver_map):
    logging.info(f"Processing FastF1 laps from {key}")
    raw = fetch_object(key)
    data = json.loads(raw)

    laps = data.get("laps", [])
    logging.info("Found %d laps", len(laps))

    rows = []
    for lap in laps:
        driver_code = lap["Driver"]
        driver_id = driver_map.get(driver_code)
        if not driver_id:
            continue

        rows.append(
            (
                race_id,
                driver_id,
                int(lap["LapNumber"]),
                int(lap["Position"]) if lap.get("Position") is not None else None,
                int(lap["LapTime"]) if lap.get("LapTime") else None,
                # (lap.get("PitInTime") or lap.get("PitOutTime")) is not None,
            )
        )

    if not rows:
        logging.warning("No laps mapped for %s", key)
        return

    with get_db_conn() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO lap_times (race_id, driver_id, lap_number, position, lap_time_ms)
            VALUES %s
            ON CONFLICT (race_id, driver_id, lap_number) DO NOTHING
            """,
            rows,
        )
        conn.commit()

    files_processed.inc()

# ---------------------------
# Main
# ---------------------------
def main():
    start_http_server(8000)

    # Step 1: Ergast (get race + driver map)
    for key in list_new_objects("jolpica"):
        race_id, driver_map = process_ergast(key)
        logging.info("Race %s inserted with %d drivers", race_id, len(driver_map))

        # Step 2: FastF1 laps
        for f1_key in list_new_objects("fastf1"):
            process_fastf1(f1_key, race_id, driver_map)

if __name__ == "__main__":
    main()
