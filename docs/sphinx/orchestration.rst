Orchestration
=============

The Autonomous ETL Agent pipeline is orchestrated by a LangGraph ``StateGraph``
defined in ``src/etl_agent/agents/orchestrator.py``.

LangGraph Overview
------------------

`LangGraph <https://github.com/langchain-ai/langgraph>`_ is a library for building
stateful, multi-actor applications with LLMs. It models the pipeline as a directed
acyclic graph (DAG) where:

* **Nodes** are async Python functions that accept a ``GraphState`` dict and return a
  dict of updates to merge into the state.
* **Edges** connect nodes. Conditional edges allow branching based on state values.
* **GraphState** (``TypedDict``) is the single shared mutable state passed between all nodes.

GraphState
----------

``GraphState`` is defined in ``src/etl_agent/core/state.py``. It is a ``TypedDict``
with ``total=False`` (all keys optional), so each node only needs to update the fields
it produces.

Key fields:

======================== ================== ====================================================
Field                    Type               Description
======================== ================== ====================================================
story                    UserStory          Input user story
run_id                   str                UUID identifying this pipeline run
story_id                 str                ID derived from the story
dry_run                  bool               If True, stops after code generation
status                   RunStatus          Current pipeline status
current_stage            str                Name of the last completed node
error_message            str | None         Set on failure
etl_spec                 ETLSpec | None     Output of StoryParserAgent
source_schema            dict | None        Column schema from Glue catalog
generated_code           str | None         Output of CodingAgent
generated_tests          str | None         Output of TestAgent
test_results             TestResult | None  Output of TestAgent
github_pr_url            str | None         Output of PRAgent
github_issue_url         str | None         Output of PRAgent
s3_artifact_url          str | None         Output of DeployAgent
token_tracker            RunTokenTracker    Accumulates token usage across all LLM calls
approval_required        bool               Set by approval_gate node
approval_granted         bool               Set by /approve API endpoint
data_classification      str                From UserStory
retry_count              int                Code-generation retry counter
max_retries              int                From Settings
======================== ================== ====================================================

Pipeline Graph
--------------

.. mermaid::

   %%{init: {'theme': 'default', 'themeVariables': {'background': '#ffffff', 'mainBkg': '#ffffff'}}}%%
   flowchart TD
       START(["▶ START"])
       PS["parse_story\nStoryParserAgent\nUserStory → ETLSpec"]
       RC["resolve_catalog\nGlue Data Catalog\nETLSpec.source → column schema"]
       GC["generate_code\nCodingAgent\nETLSpec + schema → PySpark script"]
       DRY_CHECK{dry_run?}
       DRE(["dry_run_end\n✅ DRY_RUN_COMPLETE"])
       RT["run_tests\nTestAgent\ngenerate pytest + run in subprocess"]
       RETRY{tests passed?\nor retries left?}
       AG["approval_gate\ncheck classification\n& token budget"]
       HOLD(["⏸ END\nAWAITING_APPROVAL"])
       CP["create_pr\nPRAgent\nGitHub Issue + branch + commit + PR"]
       D["deploy\nDeployAgent\n.whl → S3 → optional Airflow"]
       END(["✅ END — DONE"])

       START --> PS --> RC --> GC --> DRY_CHECK
       DRY_CHECK -->|"Yes"| DRE
       DRY_CHECK -->|"No"| RT
       RT --> RETRY
       RETRY -->|"failed, retries left"| GC
       RETRY -->|"passed"| AG
       AG -->|"approval required"| HOLD
       AG -->|"not required"| CP
       CP --> D --> END

   %% Light backgrounds, dark text, high-contrast borders
   classDef node fill:#B3D4FF,color:#000,stroke:#1A56BB,stroke-width:2px
   classDef terminal fill:#B7E1B0,color:#000,stroke:#2D6A2E,stroke-width:2px
   classDef decision fill:#FFE0A0,color:#000,stroke:#CC7700,stroke-width:2px
   classDef hold fill:#E8C6FF,color:#000,stroke:#6A1B9A,stroke-width:2px
   class PS,RC,GC,RT,AG,CP,D node
   class START,DRE,END terminal
   class DRY_CHECK,RETRY decision
   class HOLD hold

Note: The original design included a retry edge from ``run_tests`` back to
``generate_code`` when tests fail. This is managed via the ``retry_count`` field in
``GraphState`` and the routing helper ``route_after_tests()`` in ``state.py``, which
routes to ``coding_agent`` if retries remain or to ``failure`` if exhausted.

Node Descriptions
-----------------

**parse_story**
    Wraps ``StoryParserAgent.run()``. On completion, sets ``status=CODING`` and
    ``current_stage="parse_story"``.

**resolve_catalog**
    Calls ``get_catalog().get_entity_by_path(etl_spec.source.path)`` to fetch the
    exact column schema for the source dataset. Stores result as ``source_schema`` in
    state. If the catalog lookup fails or the entity is not found, ``source_schema``
    is set to ``None`` and a warning is logged — the pipeline continues with
    assumption-based code generation rather than hard-failing.

**generate_code**
    Wraps ``CodingAgent.run()``. Receives ``source_schema`` from the previous node to
    ground the generated column references in real names.

**dry_run_end**
    Terminal node reached when ``dry_run=True``. Sets ``status=DRY_RUN_COMPLETE`` and
    exits. Used for testing the parse + code generation phases without executing tests
    or touching GitHub.

**run_tests**
    Wraps ``TestAgent.run()``. Generates pytest code, executes it in a subprocess with
    a real PySpark session, and returns pass/fail results.

**approval_gate**
    Inline node (not a separate agent class). Checks data classification and token
    budget. Halts the pipeline at ``AWAITING_APPROVAL`` if either condition is met.

**create_pr**
    Wraps ``PRAgent.run()``. Creates GitHub Issue, branch, commit, and PR.

**deploy**
    Wraps ``DeployAgent.run()``. Packages ``.whl``, uploads to S3, optionally triggers
    Airflow.

Streaming Updates
-----------------

The orchestrator exposes ``stream_pipeline()`` as the public API for executing the
pipeline:

.. code-block:: python

    final_state = await stream_pipeline(
        story=user_story,
        run_id=run_id,
        on_update=_on_update_callback,
        dry_run=False,
    )

It uses ``graph.astream(..., stream_mode="updates")`` to receive an event after every
node completes. After each event, the ``on_update`` callback is called with:

* ``node_name`` — the name of the node that just completed
* ``node_output`` — the dict of state updates from that node
* ``full_state`` — the merged full state snapshot

The worker's ``_on_update`` callback writes every status change, test result, token
usage, and artifact URL to the RDS ``pipeline_runs`` table in real time. This allows
the UI to show live progress.

Worker Integration
------------------

The SQS worker (``src/etl_agent/worker.py``) is the production entry point for the
pipeline. It:

1. Long-polls SQS for a message (20-second wait time).
2. Deserialises the ``UserStory`` from the message body.
3. Updates the run status to ``PARSING`` in the database.
4. Starts a heartbeat coroutine that extends SQS message visibility every 4 minutes.
5. Calls ``stream_pipeline()`` with an ``on_update`` callback that writes every state
   update to the database.
6. On success: deletes the SQS message.
7. On failure: leaves the message visible (SQS retries it); after 3 attempts it moves
   to the DLQ.

Graceful Shutdown
~~~~~~~~~~~~~~~~~

The worker catches ``SIGTERM`` (sent by ECS when scaling in) and sets a ``_shutdown``
flag. The main polling loop checks this flag between messages, so the worker finishes
processing the current pipeline run before exiting. This prevents a pipeline from being
killed mid-run when ECS scales the service down.

Run Status Lifecycle
--------------------

A pipeline run transitions through the following statuses:

.. mermaid::

   %%{init: {'theme': 'default', 'themeVariables': {'background': '#ffffff', 'labelBackground': '#ffffff', 'stateLabelColor': '#000000', 'transitionColor': '#333333', 'lineColor': '#333333'}}}%%
   stateDiagram-v2
       direction LR
       [*] --> PENDING
       PENDING --> PARSING : worker picks up SQS message
       PARSING --> CODING : ETLSpec generated
       CODING --> TESTING : code generated
       TESTING --> CODING : tests failed, retries left
       TESTING --> PR_CREATING : tests passed
       TESTING --> AWAITING_APPROVAL : high sensitivity data\nor budget exceeded
       AWAITING_APPROVAL --> PR_CREATING : POST /runs/{id}/approve
       PR_CREATING --> DEPLOYING : GitHub PR created
       DEPLOYING --> DONE : artifact uploaded to S3
       CODING --> DRY_RUN_COMPLETE : dry_run=True

       PARSING --> FAILED : unhandled exception
       CODING --> FAILED : max retries exhausted
       TESTING --> FAILED : unhandled exception
       PR_CREATING --> FAILED : GitHub API error
       DONE --> [*]
       FAILED --> [*]
       DRY_RUN_COMPLETE --> [*]

Audit Events
------------

Every significant state transition writes an immutable audit event via
``write_audit_event()`` (``src/etl_agent/core/audit.py``). Events include:

* ``STORY_SUBMITTED`` — when the API receives a new story
* ``RUN_CREATED`` — when a run record is inserted
* ``PARSING_STARTED`` — when the worker picks up the SQS message
* ``RUN_COMPLETED`` — when the pipeline reaches ``DONE``
* ``RUN_FAILED`` — when the pipeline reaches ``FAILED``

Audit events are written to the ``audit_events`` table in PostgreSQL and are
immutable (insert-only, no updates or deletes).
