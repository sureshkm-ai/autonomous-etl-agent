Agents
======

The pipeline consists of five specialised agents, each implemented as a class that
inherits from ``ReactAgent`` (``src/etl_agent/agents/base.py``). Every agent exposes
a single async ``run(state: GraphState) -> dict`` method and is registered as a
LangGraph node in the orchestrator.

ReactAgent Base Class
---------------------

``ReactAgent`` provides two reusable loop patterns that all agents share:

**react_llm_loop** — Multi-turn LLM conversation with self-correction
    Calls the LLM with an initial message, validates the response using a caller-supplied
    ``validate`` function, and—if validation fails—injects a fix instruction and calls
    the LLM again (up to 3 attempts by default). This handles cases such as malformed JSON
    from the story parser or Python syntax errors from the code generator.

**react_tool_loop** — Async tool execution with retry
    Wraps any async callable (e.g., a GitHub API call, a PySpark subprocess) in a retry
    loop that catches specified exception types and retries up to ``max_attempts`` times.
    Handles transient network errors, GitHub rate limits, and similar flaky failures without
    failing the whole pipeline.

All LLM calls go through the Anthropic Python SDK (``anthropic.AsyncAnthropic``). The model,
max tokens, and temperature are read from ``Settings`` (``src/etl_agent/core/config.py``).

.. note::

    The ``tenacity`` library is used for exponential-backoff retries on LLM API calls
    (``@retry(stop=stop_after_attempt(3), wait=wait_exponential(...)``).

Agent 1 — StoryParserAgent
--------------------------

**Module**: ``src/etl_agent/agents/story_parser.py``

**Purpose**: Converts a natural-language ``UserStory`` into a structured ``ETLSpec``
(Pydantic model) by calling Claude and asking it to return a JSON object that matches
the ``ETLSpec`` schema.

**What it does**:

1. Queries the Glue Data Catalog (``get_catalog().list_entities()``) to get the full
   list of available datasets with their S3 paths and column schemas. This gives the
   LLM grounded context about what data is available.
2. Builds a prompt via ``build_story_parser_prompt()`` that includes the user story,
   the catalog entities, and the output S3 bucket for processed data.
3. Calls Claude via ``react_llm_loop``. If the response is not valid JSON or does not
   parse as an ``ETLSpec``, the loop injects the error and asks Claude to correct it
   (up to 3 attempts).
4. Returns ``{"etl_spec": ETLSpec(...), "status": RunStatus.CODING}`` on success.

**Key design point**: The catalog lookup in this agent (Catalog Check #1) gives the LLM
the full list of datasets so it can decide *which* datasets to use and *what* the
source/target S3 paths should be. A second catalog lookup (Catalog Check #2) happens
in the ``resolve_catalog`` orchestrator node *after* this agent, to retrieve the precise
column schema for the chosen source path.

**Retry behaviour**: LLM calls are retried up to 3 times on exception
(exponential backoff 2 s–30 s). The ``react_llm_loop`` self-correction loop runs up to
3 turns on JSON/schema validation failures.

Agent 2 — CodingAgent
---------------------

**Module**: ``src/etl_agent/agents/coding_agent.py``

**Purpose**: Generates a production-ready PySpark script from the ``ETLSpec`` produced
by the StoryParserAgent.

**What it does**:

1. Builds a prompt via ``build_code_generator_prompt()`` that includes the ``ETLSpec``,
   the column schema from the Glue catalog (``source_schema`` from ``GraphState``), any
   test failure context from a previous retry attempt, and the retry count.
2. Calls Claude via ``react_llm_loop``. If the generated Python code has a syntax error
   (checked by ``ast.parse`` via ``code_validator.validate_python_syntax()``), the loop
   injects the error and requests a corrected version.
3. Extracts the ``\`\`\`python`` block from the response as the generated pipeline code.
4. Optionally extracts a ``\`\`\`markdown`` block as a pipeline README.
5. Returns ``{"generated_code": ..., "generated_readme": ..., "status": RunStatus.TESTING}``.

**Retry behaviour**: On test failure (from the TestAgent), the orchestrator routes back
to CodingAgent with the failed test names and output injected into the prompt, giving
the model the information it needs to fix the code. Up to ``max_retries`` (default 2)
full code-generation → test-run cycles are allowed.

Agent 3 — TestAgent
-------------------

**Module**: ``src/etl_agent/agents/test_agent.py``

**Purpose**: Generates pytest tests for the generated code, executes them in a real
PySpark subprocess, and reports whether they pass.

**What it does**:

1. Builds a test generation prompt via ``build_test_generator_prompt()`` that includes
   the ``ETLSpec`` and the generated pipeline code.
2. Appends a set of critical PySpark testing rules directly to the prompt to prevent
   common LLM mistakes (e.g., calling F.col() in assertions, forgetting to chain mock
   DataFrame return values, leaving ``count()`` returning a ``MagicMock``).
3. Calls Claude via ``react_llm_loop`` to generate pytest code. Validates syntax via
   ``ast.parse`` before accepting the result.
4. Writes the generated code, tests, and an auto-injected ``conftest.py`` to a temporary
   directory and runs ``pytest`` as a subprocess with a 300-second timeout.
5. The ``conftest.py`` starts a real local PySpark ``SparkSession`` (``local[1]``) so that
   all ``pyspark.sql.functions`` calls resolve correctly without mocking.
6. Parses the pytest output to extract pass/fail counts, coverage percentage, and
   failed test names.
7. Returns ``{"generated_tests": ..., "test_results": TestResult(...), "status": ...}``.

**Retry logic**: If tests fail and ``retry_count < max_retries``, the orchestrator routes
back to CodingAgent (not TestAgent) with the failure context injected.

Agent 4 — PRAgent
-----------------

**Module**: ``src/etl_agent/agents/pr_agent.py``

**Purpose**: Creates a GitHub Issue, commits the generated code to a new branch, and
opens a Pull Request in the configured target repository.

**What it does**:

1. Calls Claude via ``react_llm_loop`` to generate a concise git commit subject line
   (≤ 72 characters, conventional commits format). Retries if the message is empty or
   too long.
2. Uses ``GitHubTools`` (``src/etl_agent/tools/github_tools.py``) with the
   ``react_tool_loop`` pattern to:

   a. Create a GitHub Issue with the user story title, description, and acceptance criteria.
   b. Create a new branch named ``etl-agent/<story_id>-<pipeline_name>``.
   c. Commit three files to the branch: the generated pipeline ``.py``, the generated
      test file, and the README.
   d. Open a Pull Request referencing the issue, with a summary of operations and test
      results.

3. Returns ``{"github_issue_url": ..., "github_pr_url": ..., "status": RunStatus.DEPLOYING}``.

**Target repository**: Set via ``GITHUB_OWNER`` and ``GITHUB_REPO`` secrets. This is a
separate repository from the ETL Agent project itself — it is the repository where the
generated pipeline code lands for review and merge.

Agent 5 — DeployAgent
---------------------

**Module**: ``src/etl_agent/agents/deploy_agent.py``

**Purpose**: Packages the generated pipeline as a Python ``.whl`` file, uploads it to S3,
and optionally triggers an Airflow DAG.

**What it does**:

1. Calls ``AWSTools.package_whl()`` to create a minimal Python wheel containing the
   generated pipeline code. Uses the ``react_tool_loop`` with up to 3 retries.
2. Uploads the ``.whl`` to the artifacts S3 bucket at
   ``artifacts/<pipeline_name>/<pipeline_name>.whl``. Uses the ``react_tool_loop`` with
   up to 3 retries on ``S3UploadError``.
3. If ``AIRFLOW_ENABLED=true`` in settings, calls the Airflow REST API (``POST /dagRuns``)
   to trigger the ``etl_pipeline`` DAG with the artifact URL as a ``conf`` parameter.
4. **Non-blocking**: any exception in the deploy agent is caught and logged, but the
   pipeline status is still set to ``DONE``. A deploy hiccup does not fail an otherwise
   successful run.

Approval Gate (Orchestrator Node)
----------------------------------

The approval gate is not a standalone agent class but an orchestrator node
(``_node_approval_gate`` in ``src/etl_agent/agents/orchestrator.py``).

It checks two conditions and sets ``approval_required = True`` if either is met:

* **Data classification**: the story has ``data_classification = confidential`` or
  ``restricted``.
* **Token budget**: the run has consumed more than ``budget_approval_threshold_pct``
  (default 75 %) of the ``max_tokens_per_run`` (default 500 000 tokens) budget.

If approval is required, the pipeline terminates at ``AWAITING_APPROVAL`` status and waits
for a human operator to call the ``POST /api/v1/runs/{run_id}/approve`` endpoint to resume.
If not required, it proceeds directly to ``create_pr``.

LLM Configuration
-----------------

All agents share the same LLM settings from ``Settings``:

=================== =======================================
Setting             Default
=================== =======================================
Model               ``claude-sonnet-4-6``
Max tokens          8 096
Temperature         0.2
Approved models     ``claude-opus-4-6``, ``claude-sonnet-4-6``, ``claude-haiku-4-5-20251001``
Fallback model      ``claude-sonnet-4-6``
=================== =======================================

LLM governance is tracked by ``RunTokenTracker`` (``src/etl_agent/core/llm_governance.py``),
which accumulates token counts and cost estimates across all agent calls within a single
pipeline run and writes per-step token snapshots to ``GraphState``.
