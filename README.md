# F1 Telemetry Aggregator — Step-by-step Plan & Architecture

**Goal:** build a small backend service that ingests F1 race/telemetry data, processes and stores aggregated metrics, exposes a simple API, and demonstrates shipping + operating practices (CI/CD, infra-as-code, monitoring, SLOs, incident handling). Minimal front-end — a tiny status page or Swagger is enough.

---

## High-level architecture (ASCII)

```
[Ergast API / Scraper] ---> [Ingest Job (Jenkins scheduled -> Docker)] ---> S3 (raw) / RDS (raw or staged)
                                                           |
                                                           v
                                           [Processing Service (Docker) on ECS Fargate]
                                                           |
                                                           v
                        -------------------------------------------------------------
                        |                       |                                   |
                   [Postgres RDS]         [Prometheus metrics endpoint]         [S3 (processed snapshots)]
                        |                       |                                   |
                        v                       v                                   v
                   [API Service (FastAPI) behind ALB / API Gateway] ---> [Grafana for dashboards]
                                                           |
                                                           v
                                                   [Users / Clients]

CI/CD: Jenkins -> build/push image to ECR -> deploy via CloudFormation (change set)

Observability: Prometheus (scrape /metrics) + Alertmanager -> Alerts to Slack/email


```

---

## Components summary

* **Ingest job** — scheduled job (Jenkins or Lambda) that fetches Ergast or scrapes race telemetry and writes raw JSON to S3 (or directly to a staging table in Postgres).
* **Processing service** — Dockerized worker that normalizes and aggregates raw data and writes to Postgres (and optionally emits snapshots to S3).
* **API service** — Dockerized FastAPI app exposing endpoints for aggregated stats.
* **Storage** — Postgres RDS for relational queries; S3 for raw/archival data.
* **CI/CD** — Jenkins builds, runs tests, pushes to ECR, then deploys CloudFormation.
* **Infra as Code** — CloudFormation (or Terraform) describes ECR, ECS Cluster/TaskDefinition, ALB, RDS, IAM roles, and Prometheus/Grafana hosting.
* **Monitoring** — Prometheus scrapes /metrics endpoints on services; Grafana shows dashboards; Alertmanager sends alerts.

---

## Step-by-step plan (detailed)

### Step 0 — Project scaffolding & account prep (1-2 hours)

**Goal:** create repositories, AWS bootstrap resources, and developer workflow.

1. Create a GitHub repo `f1-telemetry` with these top-level folders:

   * `api/` (FastAPI service)
   * `worker/` (processing service)
   * `infra/` (CloudFormation templates or Terraform)
   * `jenkins/` (Jenkinsfiles, scripts)
   * `docs/` (architecture diagram, runbook, postmortem template)

2. Branching model: `main` (deployed), `dev` (integration), feature branches.

3. AWS bootstrap (one-time):

   * Create an **ECR** repository for images.
   * Create an **S3** bucket `f1-telemetry-raw-<env>` for raw payloads.
   * Create an **RDS Postgres** instance (dev: `db.t3.micro`) in a private subnet or public for dev convenience.
   * Create IAM roles:

     * Jenkins principal with `AmazonEC2ContainerRegistryPowerUser`, `AmazonS3FullAccess` (dev), and `CloudFormationFullAccess` (or scoped CloudFormation permissions).
     * Task execution role for ECS tasks to access S3 and RDS secrets.
   * Store DB credentials in **AWS Secrets Manager**.

4. Optional: create a small VPC and security groups allowing only ALB inbound (80/443) and ECS tasks to talk to RDS on 5432.

### Step 1 — Ingestion: scheduled fetcher (2-6 hours)

**Goal:** reliably fetch F1 data and land raw payloads where they are versioned.

1. Choose ingestion mechanism: Jenkins scheduled job (simple) OR AWS Lambda + EventBridge (serverless). For learning CI/CD, use **Jenkins** to schedule a daily/5-min job.

2. Implement a small Python script `ingest/fetch_ergast.py` that:

   * Calls Ergast API (or uses a mock file for telemetry).
   * Writes raw JSON to S3 with path `raw/{date}/{source}/{timestamp}.json`.

Sample pseudo-code:

```python
import requests
import boto3
from datetime import datetime

resp = requests.get('http://ergast.com/api/f1/current/last/results.json')
if resp.ok:
    s3 = boto3.client('s3')
    key = f"raw/{datetime.utcnow().isoformat()}.json"
    s3.put_object(Bucket='f1-telemetry-raw-dev', Key=key, Body=resp.content)
```

3. Jenkins: create a job `ingest-cron` with schedule (e.g., `H/5 * * * *`) that runs a container: `python fetch_ergast.py`. Jenkinsfile example later.

4. Validate: check S3 objects; record the first ingest timestamp in the repo docs.

### Step 2 — Processing pipeline: normalization & aggregation (4-8 hours)

**Goal:** convert raw payloads into canonical DB rows and create aggregated metrics.

1. Create a worker service (`worker/`) that can run either continuously (ECS service) or as a triggered batch job (ECS RunTask or Lambda). For small scope, run it as a periodically scheduled ECS Fargate task (or run on Jenkins for simplicity).

2. Responsibilities:

   * Read raw objects from S3 (or read from staging table).
   * Parse JSON into canonical schema (drivers, races, lap\_times).
   * Upsert into Postgres.
   * Produce aggregation rows (avg lap time per driver per race, pit stop counts, fastest lap, etc.).
   * Expose Prometheus metrics for counts processed and processing duration.

3. Dockerfile (worker):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python","worker/main.py"]
```

4. Example metrics (prometheus\_client):

```python
from prometheus_client import Counter, Histogram
processed = Counter('f1_processed_files_total', 'files processed')
proc_time = Histogram('f1_processing_seconds', 'processing time seconds')

@proc_time.time()
def process_file(key):
    # parse and write to postgres
    processed.inc()
```

### Step 3 — Storage design (1-3 hours)

**Goal:** create a schema that's simple to query and demonstrates thoughtfulness.

1. Use Postgres (RDS). Example schema:

```sql
CREATE TABLE drivers (id serial PRIMARY KEY, driver_ref text UNIQUE, given_name text, family_name text, code text);
CREATE TABLE races (id serial PRIMARY KEY, season int, round int, race_name text, date date);
CREATE TABLE lap_times (id serial PRIMARY KEY, race_id int REFERENCES races(id), driver_id int REFERENCES drivers(id), lap int, time_ms int);
CREATE TABLE aggregations (id serial PRIMARY KEY, driver_id int, race_id int, avg_lap_ms int, pit_stops int, fastest_lap_ms int);
```

2. Indexing: index `lap_times(race_id, driver_id)` and `aggregations(driver_id)` for queries.

3. Store heavy raw JSON in S3 (cost-effective) and keep relational querying in Postgres.

### Step 4 — API service (4-6 hours)

**Goal:** create a minimal API that returns useful aggregated stats and a `/metrics` endpoint.

1. FastAPI skeleton (`api/`): endpoints like:

   * `GET /drivers/{id}/stats`
   * `GET /races/{id}/lap-times`
   * `GET /healthz`
   * `GET /metrics` (Prometheus)

2. Example FastAPI + Prometheus snippet:

```python
from fastapi import FastAPI, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

app = FastAPI()

@app.get('/metrics')
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

3. Dockerfile same layout as worker but runs Uvicorn:

```dockerfile
CMD ["uvicorn","api.main:app","--host","0.0.0.0","--port","8000"]
```

4. Health checks: `/healthz` returns 200 and checks DB connectivity.

5. Authentication: for a public demo keep it simple (API key header) so "real users" can hit it without exposing internal DB.

### Step 5 — Deploy infra with CloudFormation (4-8 hours)

**Goal:** make everything reproducible with a template and one deploy command.

1. Key infra resources to define (start minimal):

   * ECR repository(s)
   * ECS Cluster + TaskDefinitions (Fargate)
   * Application Load Balancer + Target Group
   * RDS Postgres
   * S3 buckets
   * IAM roles (task execution, service roles), Secrets Manager entry for DB password
   * Security Groups & VPC (or reuse existing)

2. Use CloudFormation `Parameters` for `ImageTag`, `DBPasswordSecretArn`, `VPC`.

3. Deploy flow from Jenkins: create a CloudFormation change set and execute it (safer than direct stack update). Example CLI snippet:

```bash
aws cloudformation deploy \
  --stack-name f1-telemetry-dev \
  --template-file infra/stack.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides ImageTag=$IMAGE_TAG
```

4. For simplicity & speed in a personal project, prefer **ECS Fargate** over EKS — less infra to manage but still production-like.

### Step 6 — CI/CD with Jenkins (3-6 hours)

**Goal:** show that code changes produce builds that are tested and deployed automatically.

1. Jenkins pipeline stages (example `Jenkinsfile`):

   * Checkout
   * Unit tests (`pytest`)
   * Build Docker image
   * Push to ECR (login via `aws ecr get-login-password`)
   * CloudFormation deploy (change set) or call a deploy script

2. Example Jenkinsfile (simplified):

```groovy
pipeline {
  agent any
  environment { AWS_REGION='us-east-1' }
  stages {
    stage('Checkout') { steps { checkout scm } }
    stage('Test') { steps { sh 'pytest -q' } }
    stage('Build & Push') { steps { sh 'docker build -t $ECR:$BUILD_NUMBER . && aws ecr get-login-password | docker login --username AWS --password-stdin $ECR && docker push $ECR:$BUILD_NUMBER' } }
    stage('Deploy') { steps { sh 'aws cloudformation deploy --stack-name f1-telemetry --template-file infra/stack.yml --parameter-overrides ImageTag=$BUILD_NUMBER --capabilities CAPABILITY_NAMED_IAM' } }
  }
}
```

3. Make pipeline logs public (or keep in Jenkins with links) as proof of shipping.

### Step 7 — Observability: Prometheus, Grafana, and Alerts (3-6 hours)

**Goal:** collect metrics, show dashboards, and trigger alerts.

1. Each service exposes metrics at `/metrics` via `prometheus_client` (Python). Suggested metrics:

   * `http_requests_total{method,endpoint,status}`
   * `http_request_latency_seconds` (Histogram) with labels
   * `f1_processed_files_total`
   * `f1_processing_seconds`

2. Run Prometheus as an ECS task or on a small EC2 instance. Example `scrape_configs`:

   ```yaml
   scrape_configs:
     - job_name: 'f1-telemetry'
       metrics_path: /metrics
       static_configs:
         - targets: ['api:8000','worker:8000']
   ```

3. Deploy Grafana (ECS or EC2) and connect it to Prometheus. Create dashboards for:

   * Ingest success/fail counts
   * Aggregation latency trends
   * API latency and error rate
   * Overall system uptime

4. Configure Alertmanager to send alerts to Slack/email when:

   * API error rate > 5% for 5 minutes
   * Processing duration spikes above a threshold
   * RDS instance unavailable or high CPU usage

---

### Step 8 — SLOs, runbook, and incident simulation (2-4 hours)

**Goal:** practice operational discipline and document handling of failures.

1. Define 2–3 SLOs, e.g.:

   * 99% of ingestion jobs succeed within 10 minutes of schedule.
   * API p95 latency < 500 ms.
   * Data processing lag < 10 minutes.

2. Create a **runbook** in `docs/` covering:

   * Common failures (S3 permissions, DB connectivity, ECS task crash).
   * Commands to restart tasks or roll back CloudFormation.
   * Contact points for alerts.

3. Perform a small incident simulation:

   * Stop the worker service or break DB creds.
   * Confirm alert fires, follow runbook steps, and restore service.

---

### Step 9 — Polish & optional extras (time varies)

**Optional enhancements:**

* Add a simple front-end (React or static HTML) served via S3 + CloudFront showing driver stats or last ingest status.
* Enable HTTPS with ACM certificates on the ALB.
* Add caching with Redis or ElastiCache if API performance needs boosting.
* Add unit and integration tests with coverage reporting in CI.
* Integrate IaC linting (cfn-lint or checkov) and Docker image scanning.
* Automate cost monitoring (e.g., AWS Budgets alerts).

---

**End of Plan**
