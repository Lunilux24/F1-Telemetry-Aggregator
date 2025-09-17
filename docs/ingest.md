# Ingest Job Documentation

## What It's Doing
The ingest job is meant to pull data from the Ergast/Jolpica API and FastF1 Python Library so that the raw data can be stored in an AWS S3 Bucket prior to the processing stage. I am using the 

- [Ergast API]() to pull historical and current F1 results in JSON form
- [FastF1 Library]() to pull lap/telemetry data

The ```fastf1_ingest.py``` file is what is being run by Jenkins during the cron job. It is scheduled to run daily at noon, ingesting the data before uploading directly to the S3 bucket. Looking at the ingest script, we can see the distinction between pulling from the FastF1 Python Library and the Ergast/Jolpica API. Let's take a closer look at the script!

## How It Works

The script performs the following steps:

1. **Argument Parsing & Environment Setup**: Reads command-line arguments (or environment variables) to determine the S3 bucket, AWS region, data sources, and other options.
2. **Session Setup**: Configures a robust HTTP session for API requests, with retry logic and custom headers.
3. **Data Fetching**:
   - Fetches race results from the Jolpica/Ergast API.
   - Optionally fetches telemetry and lap data from the FastF1 library for the most recent completed race.
4. **Data Upload**: Uploads the fetched data as JSON files to a specified AWS S3 bucket, organizing them by date and source.
5. **Error Handling & Retries**: Implements retry logic for robustness, logging failures and retrying as needed.

### Key Functions
- `make_requests_session()`: Sets up a requests session with retry logic.
- `fetch_jolpica()`: Fetches race results from the Jolpica/Ergast API.
- `fetch_fastf1()`: Fetches telemetry and lap data for the latest race using FastF1.
- `write_to_s3()`: Uploads data to AWS S3 with appropriate metadata.
- `ingest_and_upload()`: Handles the process of uploading a single data source to S3.
- `main()`: Orchestrates the overall workflow, including argument parsing, data fetching, and uploading.

### Data Flow
- The script can be run with various arguments to control which data sources are ingested and where the data is uploaded.
- Data is always uploaded to S3 in a structured path: `raw/<date>/<source>/<timestamp>.json`.
- Metadata about the source and ingest time is attached to each S3 object.

---


