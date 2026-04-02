API Reference
=============

The ETL Agent exposes a versioned REST API at ``/api/v1/``. All endpoints require
an ``X-API-Key`` header (value set via the ``API_KEY`` secret/environment variable).

The interactive Swagger UI is available at ``http://<host>/docs``.

Authentication
--------------

All requests (except ``GET /api/v1/health``) require:

.. code-block:: http

    X-API-Key: <your-api-key>

Returns ``401 Unauthorized`` if missing or incorrect.

Request body size is limited to 32 KB (configurable via ``MAX_REQUEST_BODY_BYTES``).

Health Check
------------

``GET /api/v1/health``
~~~~~~~~~~~~~~~~~~~~~~

Returns the application health status. Does not require authentication.

**Response** ``200 OK``:

.. code-block:: json

    {
        "status": "ok",
        "database": "ok",
        "version": "1.0.0"
    }

Stories
-------

``POST /api/v1/stories``
~~~~~~~~~~~~~~~~~~~~~~~~~

Submit a user story to the ETL Agent pipeline. Returns immediately with a ``run_id``.
The pipeline runs asynchronously in a worker.

**Query parameters**:

* ``dry_run`` (bool, default ``false``) — if ``true``, runs only ``parse_story`` and
  ``generate_code`` stages without running tests, creating a PR, or deploying.

**Request body** (``application/json``):

.. code-block:: json

    {
        "title": "string (required, max 256 chars)",
        "description": "string (required, max 2000 chars)",
        "acceptance_criteria": ["string", "..."]
    }

**Response** ``202 Accepted``:

.. code-block:: json

    {
        "run_id": "uuid",
        "story_id": "uuid",
        "status": "PENDING",
        "data_classification": "internal",
        "execution_mode": "sqs",
        "dry_run": false,
        "message": "Pipeline queued. Track at GET /api/v1/runs/<run_id>"
    }

**Execution modes**:

* ``sqs`` — production mode (``SQS_QUEUE_URL`` is configured); message published to SQS,
  a worker Fargate task picks it up.
* ``background_task`` — local/dev mode (``SQS_QUEUE_URL`` empty); pipeline runs inside
  the API process as a FastAPI ``BackgroundTask``.

Pipeline Runs
-------------

``GET /api/v1/runs``
~~~~~~~~~~~~~~~~~~~~~

List all pipeline runs, most recent first.

**Query parameters**:

* ``limit`` (int, default 100)
* ``offset`` (int, default 0)

**Response** ``200 OK``:

.. code-block:: json

    [
        {
            "run_id": "uuid",
            "story_id": "uuid",
            "story_title": "Filter Delivered Orders",
            "status": "DONE",
            "current_stage": "deploy",
            "submitted_at": "2025-06-01T10:00:00",
            "started_at": "2025-06-01T10:00:05",
            "completed_at": "2025-06-01T10:12:30",
            "github_pr_url": "https://github.com/org/repo/pull/42",
            "github_issue_url": "https://github.com/org/repo/issues/41",
            "s3_artifact_url": "s3://etl-agent-artifacts-production/artifacts/...",
            "test_results": {
                "passed": true,
                "passed_tests": 5,
                "total_tests": 5,
                "coverage_pct": 87.0
            },
            "retry_count": 0,
            "total_input_tokens": 12000,
            "total_output_tokens": 4000,
            "total_cost_usd": 0.08,
            "budget_pct": 3.2,
            "approval_required": false,
            "data_classification": "internal"
        }
    ]

``GET /api/v1/runs/{run_id}``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get the full status and all fields for a single run.

**Path parameters**:

* ``run_id`` (string, required)

**Response** ``200 OK``: same schema as a single item from ``GET /api/v1/runs``.

**Response** ``404 Not Found``: if the run ID does not exist.

``POST /api/v1/runs/{run_id}/approve``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Resume a pipeline that is halted at ``AWAITING_APPROVAL``.

**Path parameters**:

* ``run_id`` (string, required)

**Request body**:

.. code-block:: json

    {
        "actor": "suresh",
        "rationale": "Reviewed data classification — approved for PR creation."
    }

**Response** ``200 OK``:

.. code-block:: json

    {
        "run_id": "uuid",
        "status": "PR_CREATING",
        "message": "Pipeline resumed"
    }

Data Catalog
------------

``GET /api/v1/catalog``
~~~~~~~~~~~~~~~~~~~~~~~~

Returns all datasets registered in the AWS Glue Data Catalog.

**Response** ``200 OK``:

.. code-block:: json

    [
        {
            "name": "orders",
            "display_name": "orders",
            "description": "",
            "s3_path": "s3://etl-agent-raw-prod/olist/orders/",
            "format": "csv",
            "data_classification": "internal",
            "columns": [
                {"name": "order_id", "type": "string"},
                {"name": "customer_id", "type": "string"},
                {"name": "order_status", "type": "string"},
                "..."
            ]
        }
    ]

``GET /api/v1/catalog/{name}``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns a single catalog entity by Glue table name.

**Response** ``404 Not Found``: if the table name does not exist.

``POST /api/v1/catalog``
~~~~~~~~~~~~~~~~~~~~~~~~~

Manually register a new entity in the Glue catalog. Useful for datasets not covered
by the Glue Crawler.

**Request body**:

.. code-block:: json

    {
        "name": "my_dataset",
        "display_name": "My Dataset",
        "description": "Optional description",
        "s3_path": "s3://my-bucket/my-prefix/",
        "format": "parquet",
        "data_classification": "internal",
        "columns": [
            {"name": "id", "type": "string"},
            {"name": "value", "type": "double"}
        ]
    }

``PUT /api/v1/catalog/{name}``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Update an existing catalog entity.

``DELETE /api/v1/catalog/{name}``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Delete a catalog entity from the Glue database.

Error Responses
---------------

All endpoints return a standard error body on failure:

.. code-block:: json

    {
        "detail": "Error message describing what went wrong"
    }

Common status codes:

======= ===================================================
Code    Meaning
======= ===================================================
200     Success
202     Accepted (async operation queued)
400     Validation error (malformed request body)
401     Missing or invalid API key
404     Resource not found
413     Request body exceeds size limit
422     Unprocessable entity (Pydantic validation failure)
500     Internal server error
======= ===================================================

Web UI
------

The application ships a single-page web interface served at ``GET /``. It is a
pure HTML/JavaScript page (no build step, no npm) served as a static file from
``src/etl_agent/static/index.html``.

The UI has three views:

* **Dashboard** — lists all pipeline runs with status badges and live refresh.
* **New Pipeline** — form to submit a new user story (Title, Description,
  Acceptance Criteria).
* **Data Catalog** — lists all Glue catalog entities with column details.
