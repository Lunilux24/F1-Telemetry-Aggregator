# Batch Job Documentation

## What It's Doing
The batch job is designed to take the filtered data from the ingest job that is being stored in the S3 bucket, parse it and prepare it for entry into the Postgres database. The batch job was integrated into the Jenkinsfile so that when the cron job is runs and executes the ingestion step, the batch job will run after the upload to the S3 bucket. 

## How It Works
The script performs the following steps:

1. **Connection & Configuration**: Loads the environment variables and establishes the connection with the Postgres database. Also initializes the Prometheus metrics and server for monitoring.
2. **Fetching Data**: Connects to S3 yielding the keys of objects under the correct prefix (in this case: /raw). S3 object is then returned, its data decoded and read as raw JSON data. 
3. **Processing Step**:
   - Processes the data from Ergast before sorting through it and executing SQL statements to insert into relevant tables.
   - Processes the data from FastF1 before sorting through it and executing SQL statements to insert into relevant tables.

