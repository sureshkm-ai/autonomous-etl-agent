# API Reference

The Autonomous ETL Agent exposes a versioned REST API at `/api/v1/`. All endpoints (except `/health`) require an `X-API-Key` header.

Interactive docs are available at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`.

---

## Authentication

All protected endpoints require:

```
X-API-Key: <your-api-key>
```

Set `API_KEY` in your `.env` file. The health endpoint is publicly accessible.

---

## Base URL

```
http://localhost:8000/api/v1
```

---

## Endpoints

### Health

#### `GET /health`

Returns the service health status. No authentication required.

**Response 200**

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

### Stories

#### `POST /stories`

Submit a user story (YAML or JSON) to start an ETL pipeline run. The request is accepted immediately and the pipeline runs asynchronously as a background task.

**Request Body**

```json
{
  "story_yaml": "id: rfm_analysis\ntitle: RFM ...",
  "deploy": true,
  "require_approval": false,
  "dry_run": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `story_yaml` | string | ✅ | — | YAML or JSON string representing the user story |
| `deploy` | boolean | ❌ | `true` | Trigger Airflow scheduling after PR creation |
| `require_approval` | boolean | ❌ | `false` | Pause pipeline before PR creation for human approval |
| `dry_run` | boolean | ❌ | `false` | Generate code and run tests, but skip GitHub and Airflow |

**Response 202 Accepted**

```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING",
  "message": "Pipeline run accepted. Use GET /runs/{run_id} to track progress."
}
```

**Response 422 Unprocessable Entity** — Invalid story format.

**Response 429 Too Many Requests** — Rate limit exceeded (10 requests per minute per IP).

---

### Runs

#### `GET /runs`

List all pipeline runs with optional filtering.

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | integer | `0` | Pagination offset |
| `limit` | integer | `50` | Max records to return (max 200) |
| `status` | string | — | Filter by status (e.g. `DONE`, `FAILED`) |

**Response 200**

```json
[
  {
    "run_id": "550e8400-...",
    "story_id": "rfm_analysis",
    "pipeline_name": "rfm_analysis",
    "status": "DONE",
    "retry_count": 0,
    "tests_passed": 12,
    "tests_failed": 0,
    "coverage_pct": 87.4,
    "github_issue_url": "https://github.com/org/repo/issues/42",
    "github_pr_url": "https://github.com/org/repo/pull/43",
    "s3_artifact_url": "s3://etl-agent-artifacts/rfm_analysis/...",
    "airflow_dag_run_id": "manual__2025-01-01T00:00:00",
    "awaiting_approval": false,
    "error_message": null,
    "created_at": "2025-01-01T10:00:00Z",
    "updated_at": "2025-01-01T10:05:30Z"
  }
]
```

---

#### `GET /runs/{run_id}`

Get details for a single pipeline run.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `run_id` | UUID | Pipeline run identifier |

**Response 200** — Same structure as individual item in `GET /runs`.

**Response 404** — Run not found.

---

#### `GET /runs/{run_id}/logs`

Stream live log events for a running pipeline using **Server-Sent Events (SSE)**.

**Response** — `text/event-stream`

Each SSE event is a JSON object:

```
data: {"log": "[story_parser] Parsed ETLSpec: rfm_analysis", "status": "PARSING", "timestamp": "2025-01-01T10:00:01Z"}

data: {"log": "[coding_agent] Generated 147 lines of PySpark code", "status": "CODING"}

data: {"log": "[test_agent] 12 passed, 0 failed — coverage: 87.4%", "status": "TESTING", "tests_passed": 12, "coverage_pct": 87.4}

data: {"log": "[pr_agent] PR created: https://github.com/...", "status": "DONE", "github_pr_url": "https://..."}
```

The stream closes automatically when `status` is `DONE` or `FAILED`.

**JavaScript Example**

```javascript
const es = new EventSource('/api/v1/runs/<run_id>/logs', {
  headers: { 'X-API-Key': 'your-key' }
});

es.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.log);
  if (data.status === 'DONE' || data.status === 'FAILED') {
    es.close();
  }
};
```

---

#### `POST /runs/{run_id}/approve`

Approve a pipeline that is paused at `AWAITING_APPROVAL`. This triggers PR creation.

**Response 200**

```json
{ "run_id": "...", "status": "PR_CREATING" }
```

**Response 400** — Run is not in `AWAITING_APPROVAL` state.

---

#### `POST /runs/{run_id}/reject`

Reject a pipeline that is paused at `AWAITING_APPROVAL`. This marks the run as `FAILED`.

**Response 200**

```json
{ "run_id": "...", "status": "FAILED" }
```

---

## Status Flow

```
PENDING → PARSING → CODING → TESTING ──→ AWAITING_APPROVAL ──→ PR_CREATING → DEPLOYING → DONE
                                  │                                    │
                                  └──── (retry if tests fail) ─────────┘
                                  └──── FAILED (max retries exceeded)
```

| Status | Description |
|--------|-------------|
| `PENDING` | Run accepted, not yet started |
| `PARSING` | StoryParser agent is processing the user story |
| `CODING` | CodingAgent is generating PySpark code |
| `TESTING` | TestAgent is running generated tests |
| `AWAITING_APPROVAL` | Paused for human review (if `require_approval=true`) |
| `PR_CREATING` | PRAgent is creating GitHub Issue + PR |
| `DEPLOYING` | DeployAgent is uploading to S3 and triggering Airflow |
| `DONE` | Pipeline completed successfully |
| `FAILED` | Pipeline failed (see `error_message` field) |

---

## Rate Limiting

The API is rate-limited to **10 requests per minute** per IP address on the `POST /stories` endpoint. On exceeding the limit, the server returns:

```
HTTP 429 Too Many Requests
Retry-After: 60
```

---

## Error Responses

All error responses follow the standard FastAPI format:

```json
{
  "detail": "Human-readable error description"
}
```

Common HTTP status codes:

| Code | Meaning |
|------|---------|
| `400` | Bad request (e.g. invalid state transition) |
| `401` | Missing or invalid API key |
| `404` | Run not found |
| `422` | Validation error (invalid request body) |
| `429` | Rate limit exceeded |
| `500` | Internal server error |

---

## CLI Alternative

The same pipeline can be triggered from the command line:

```bash
# Run a story file
etl-agent run --story config/story_examples/rfm_analysis.yaml

# Dry run (no GitHub/Airflow)
etl-agent run --story my_story.yaml --dry-run --verbose

# Start the API server
etl-agent serve
```
