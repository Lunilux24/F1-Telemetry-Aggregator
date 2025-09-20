import os
import sys
import time
from fastf1.core import SessionResults
import requests
import argparse
import logging
import json
import boto3
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from dotenv import load_dotenv
from datetime import datetime, timezone

import fastf1

load_dotenv()
DEFAULT_JOLPICA_URL = os.environ.get("JOLPICA_URL", "http://api.jolpi.ca/ergast/f1/current/last/results.json")


def make_requests_session(retries=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504)):
    s = requests.Session()
    r = Retry(total=retries, backoff_factor=backoff_factor,
              status_forcelist=status_forcelist,
              allowed_methods=frozenset(['GET']))
    adapter = HTTPAdapter(max_retries=r)
    s.mount('http://', adapter)
    s.mount('https://', adapter)
    s.headers.update({'User-Agent': 'f1-telemetry-ingest/1.0 (+bbeshry@outlook.com)'})
    return s

def safe_timestamp():
    return int(time.time())

def write_to_s3(bucket, key, body, region='us-east-2', metadata=None):
    s3 = boto3.client('s3', region_name=region) if region else boto3.client('s3')
    kwargs = {'Bucket': bucket, 'Key': key, 'Body': body, 'ContentType': 'application/json'}
    if metadata:
        kwargs['Metadata'] = metadata
    s3.put_object(**kwargs)


def fetch_url(session, url, timeout=20):
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content

def fetch_jolpica(session, url):
    logging.info(f"Fetching Jolpica data from: {url}")
    return fetch_url(session, url)

def fetch_fastf1():
    logging.info("Fetching FastF1 session data (latest race)")
    fastf1.Cache.enable_cache('/tmp/f1_cache')
    events = fastf1.get_event_schedule(2025)

    last_completed = events[events["EventDate"] < pd.Timestamp.now()].iloc[-1]
    # Most recent COMPLETED race of the season
    session = fastf1.get_session(last_completed["EventDate"].year,
                             last_completed["EventName"],
                             "R")
    # Most recent race of the season
    # session = fastf1.get_session(datetime.now().year, 'Last', 'R')
    session.load()

    # TELEMETRY DATA (Can Modify)
    data = {
        "laps": json.loads(session.laps.to_json(orient="records")),
        "weather": json.loads(session.weather_data.to_json(orient="records")),
        "results": json.loads(session.results.to_json(orient="records"))
    }
    return json.dumps(data).encode('utf-8')

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--bucket', '-b', default=os.environ.get('F1_S3_BUCKET'),
                   help='S3 bucket name (or set F1_S3_BUCKET env var)')
    p.add_argument('--region', '-r', default=os.environ.get('AWS_REGION'),
                   help='AWS region (optional)')
    p.add_argument('--jolpica-url', default=DEFAULT_JOLPICA_URL,
                   help='Jolpica/Ergast-compatible URL to fetch (optional)')
    p.add_argument('--include-fastf1', action='store_true',
                   help='If set, also fetch FastF1 telemetry')
    p.add_argument('--mock-file', help='If provided, read JSON from this file instead of network')
    p.add_argument('--retries', type=int, default=3, help='Retries for overall operation')
    return p.parse_args()

def ingest_and_upload(bucket, region, source, body):
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    ts = safe_timestamp()
    key = f"raw/{date}/{source}/{ts}.json"
    metadata = {'source': source, 'ingest_time_utc': str(ts)}
    logging.info("Uploading to s3://%s/%s", bucket, key)
    write_to_s3(bucket, key, body, region=region, metadata=metadata)
    logging.info("Upload OK. Key=%s", key)
    print(key)

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    args = parse_args()

    if not args.bucket:
        logging.error("S3 bucket name is required. Please provide --bucket or set F1_S3_BUCKET environment variable.")
        sys.exit(2)
    
    session = make_requests_session()

    for attempt in range(1, args.retries + 1):
        try:
            if args.mock_file:
                logging.info(f"Using mock file: {args.mock_file}")
                body = open(args.mock_file, 'rb').read()
                ingest_and_upload(args.bucket, args.region, 'mock', body)
            else:
                jolpica_body = fetch_jolpica(session, args.jolpica_url)
                ingest_and_upload(args.bucket, args.region, 'jolpica', jolpica_body)
                if args.include_fastf1:
                    f1_body = fetch_fastf1()
                    ingest_and_upload(args.bucket, args.region, 'fastf1', f1_body)
            return 0

        except Exception as exc:
            logging.exception("Attempt %s/%s failed: %s", attempt, args.retries, exc)
            if attempt < args.retries:
                sleep = attempt * 5
                logging.info("Retrying in %s seconds...", sleep)
                time.sleep(sleep)
            else:
                logging.error("All attempts failed.")
                return 1

if __name__ == '__main__':
    sys.exit(main())
