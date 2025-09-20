import imp
import os
import json
import logging
import boto3
import psycopg2
from psycopg2.extras import execute_values
from prometheus_client import Counter, Histogram, start_http_server
from dotenv import load_dotenv
from requests import get

# Prometheus metrics
files_processed = Counter("f1_files_processed_total", "Number of raw files processed")
processing_time = Histogram("f1_processing_seconds", "Time taken to process a file")

# AWS/DB Config
load_dotenv()
F1_S3_BUCKET = os.environ["F1_S3_BUCKET"]
DB_HOST = os.environ["DB_HOST"]
DB_NAME = os.environ.get("DB_NAME", "")
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASS"]
DB_PORT = int(os.environ.get("DB_PORT", 5432))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# AWS/DB helper functions
def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )

def list_new_objects(source_prefix):
    """List objects in S3 under raw/{date}/{source}/"""
    s3 = boto3.client("s3")
    resp = s3.list_objects_v2(Bucket=F1_S3_BUCKET, Prefix="raw/")
    for obj in resp.get("Contents", []):
        if source_prefix in obj["Key"]:
            yield obj["Key"]

def fetch_object(key):
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=F1_S3_BUCKET, Key=key)
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
                int(lap["LapTime"]) if lap.get("LapTime") is not None else None,
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
        
        cur.execute(
            """
            INSERT INTO aggregations (driver_id, race_id, avg_lap_ms, fastest_lap_ms)
            SELECT 
                driver_id,
                race_id,
                AVG(lap_time_ms) FILTER (WHERE lap_time_ms IS NOT NULL)::INT,
                MIN(lap_time_ms)
            FROM lap_times
            WHERE race_id = %s
            GROUP BY driver_id, race_id
            ON CONFLICT (driver_id, race_id)
            DO UPDATE SET 
                avg_lap_ms = EXCLUDED.avg_lap_ms,
                fastest_lap_ms = EXCLUDED.fastest_lap_ms;
            """,
            (race_id,)
        )

        weather = data.get("weather", [])
        if weather:
            weather_rows = [
                (
                    race_id,
                    int(sample["Time"]),
                    float(sample["AirTemp"]) if sample.get("AirTemp") is not None else None,
                    float(sample["Humidity"]) if sample.get("Humidity") is not None else None,
                    float(sample["Pressure"]) if sample.get("Pressure") is not None else None,
                    bool(sample["Rainfall"]) if sample.get("Rainfall") is not None else None,
                    float(sample["TrackTemp"]) if sample.get("TrackTemp") is not None else None,
                    int(sample["WindDirection"]) if sample.get("WindDirection") is not None else None,
                    float(sample["WindSpeed"]) if sample.get("WindSpeed") is not None else None,
                )
                for sample in weather
            ]

            execute_values(
                cur,
                """
                INSERT INTO weather (race_id, sample_time_ms, air_temp, humidity, pressure, rainfall, track_temp, wind_direction, wind_speed)
                VALUES %s
                ON CONFLICT DO NOTHING
                """,
                weather_rows,
            )

        results = data.get("results", [])
        if results:
            result_rows = [
                (
                    race_id,
                    driver_map.get(res["Driver"]),
                    res.get("TeamId"),
                    int(res["Position"]) if res.get("Position") is not None else None,
                    float(res["Points"]) if res.get("Points") is not None else None,
                    res.get("Status"),
                    int(res["RaceTime"]) if res.get("RaceTime") is not None else None,
                    int(res["NumberOfPitStops"]) if res.get("NumberOfPitStops") is not None else 0,
                )
                for res in results
                if driver_map.get(res["Driver"])
            ]

            execute_values(
                cur,
                """
                INSERT INTO results (race_id, driver_id, team_id, position, points, status, race_time_ms, pit_stops)
                VALUES %s
                ON CONFLICT (race_id, driver_id) DO UPDATE SET
                team_id = EXCLUDED.team_id,
                position = EXCLUDED.position,
                points = EXCLUDED.points,
                status = EXCLUDED.status,
                race_time_ms = EXCLUDED.race_time_ms,
                pit_stops = EXCLUDED.pit_stops;
                """,
                result_rows,
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
