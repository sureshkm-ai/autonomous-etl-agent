# Evaluation Plan — Autonomous ETL Agent

> Based on the Anthropic framework: [Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

---

## Framework Summary

The Anthropic eval framework defines the following core terminology:

- **Task** — a single test with defined inputs and success criteria
- **Trial** — one execution attempt; run multiple trials to handle LLM non-determinism
- **Grader** — logic that scores one aspect of agent performance
- **Transcript** — the full record of a trial (outputs, tool calls, intermediate state)
- **Outcome** — the final environment state at the end of a trial

Three grader types are used throughout this plan:

| Grader Type | Strengths | Weaknesses |
|---|---|---|
| **Code-based** | Fast, objective, deterministic | Brittle to valid output variations |
| **Model-based** | Flexible, handles nuance and language | Non-deterministic, needs calibration |
| **Human** | Gold-standard quality | Expensive and slow |

Two key metrics address non-determinism:

- **pass@k** — at least one success in k attempts (useful for single-shot quality gates)
- **pass^k** — all k attempts succeed (required for customer-facing reliability)

---

## Eval 1 — StoryParserAgent

The most critical agent: a bad parse corrupts every downstream step.

### 1.1 ETLSpec Field Accuracy

**What:** Given a natural-language user story, does the output `ETLSpec` contain the correct `source.path`, `target.path`, `operations`, and `transformations`?

**How:** Build a golden dataset of 20–30 Olist-based stories with hand-verified ETLSpecs. Compare each field programmatically.

**Grader:** Code-based — exact match on `source.path`, `target.path`; set-intersection score on `operations` and `transformations`.

**Metric:** pass^3 > 95%

---

### 1.2 Source / Target Path Extraction

**What:** Does the parser correctly resolve the referenced Olist dataset to its S3 path? For example, "orders data" → `s3://etl-agent-raw-prod/olist/orders/`.

**How:** Create a mapping of common natural-language dataset references to expected S3 paths. Run the parser on stories using each dataset.

**Grader:** Code-based — string match against the known path map.

**Metric:** pass^3 = 100% (zero path hallucinations)

---

### 1.3 Hallucination Check

**What:** Does the parser invent column names or table names that don't exist in the Glue Data Catalog?

**How:** After parsing, cross-reference every column name appearing in `etl_spec.transformations` and `etl_spec.operations` against the real Glue schema for that dataset.

**Grader:** Code-based — zero tolerance; any invented column name is a failure.

**Metric:** pass^3 = 100%

---

### 1.4 Operation Classification

**What:** Does the parsed `operations` list correctly reflect the story's intent (FILTER, JOIN, AGGREGATE, DEDUPE, etc.)?

**How:** Golden stories each have a labelled expected operation set. Measure precision and recall of the predicted set.

**Grader:** Code-based — F1 score on operation set per story.

**Metric:** Average F1 > 0.90

---

### 1.5 Retry Recovery Rate

**What:** When the LLM returns malformed JSON (simulated by injecting a bad response on attempt 1), does the `react_llm_loop` recover on attempt 2 or 3?

**How:** Mock the first LLM response to return invalid JSON; allow subsequent attempts to use the real LLM.

**Grader:** Code-based — assert `retry_count > 0` AND final `status != FAILED`.

**Metric:** pass@3 = 100%

---

## Eval 2 — CodingAgent

### 2.1 Syntax Validity

**What:** Does every generated PySpark script pass `ast.parse()` without a `SyntaxError`?

**How:** Run `ast.parse()` on `generated_code` for every trial. This must be a zero-tolerance continuous check.

**Grader:** Code-based.

**Metric:** pass^3 = 100%

---

### 2.2 PySpark Runtime Correctness

**What:** Does the generated code run without raising exceptions against a small real sample of the Olist data?

**How:** Execute the generated script in a local Spark session with a 100-row sample of the relevant Olist dataset. Check that it completes without a runtime error and produces a non-empty output DataFrame.

**Grader:** Code-based — subprocess exit code 0, no exception in stdout/stderr, output row count > 0.

**Metric:** pass@3 > 90%

---

### 2.3 Schema Grounding

**What:** When `source_schema` is provided by the `resolve_catalog` node, does the generated code reference only columns that actually exist in that schema?

**How:** Parse the generated code's AST for all string literals used as column references (via `df["col"]`, `F.col("col")`, `.select("col")` patterns). Cross-check each against the `source_schema` dict.

**Grader:** Code-based — any reference to a non-existent column is a failure.

**Metric:** pass^3 = 100%

---

### 2.4 Acceptance Criteria Coverage

**What:** Does the generated code implement each acceptance criterion stated in the user story?

**How:** Pass the user story, its acceptance criteria, and the generated code to an LLM evaluator with a rubric. Score each criterion 0 (not implemented), 0.5 (partially implemented), or 1 (fully implemented).

**Grader:** Model-based rubric.

**Metric:** Average per-criterion score > 0.80

---

### 2.5 Code Quality

**What:** Is the generated code idiomatic PySpark? Does it avoid anti-patterns such as `.toPandas()` loops, collecting large DataFrames, or missing `.alias()` calls?

**How:** Define a static checklist of anti-patterns as regex or AST rules. Additionally, use a model-based grader for overall readability and idiomaticity.

**Grader:** Code-based (anti-pattern rules) + model-based rubric (quality score 1–5).

**Metric:** Zero anti-pattern violations; average quality score > 3.5

---

### 2.6 Retry Improvement Rate

**What:** When fed back failed test output, does the regenerated code fix the failing tests?

**How:** Record `test_results` before and after a coding retry. Score = (tests fixed) / (tests initially failing).

**Grader:** Code-based.

**Metric:** Average fix rate > 70% per retry cycle

---

## Eval 3 — TestAgent

The TestAgent is itself generating tests — so the eval question is whether the generated tests are *good* tests, not just whether they pass.

### 3.1 Test Syntax Validity

**What:** Does every generated test file pass `ast.parse()`?

**Grader:** Code-based — zero tolerance.

**Metric:** pass^3 = 100%

---

### 3.2 Acceptance Criteria Test Coverage

**What:** Does the generated test suite include at least one test for each acceptance criterion and each declared transformation in the ETL spec?

**How:** Pass the ETL spec, the acceptance criteria, and the generated test code to an LLM evaluator. Score whether each criterion has a corresponding assertion.

**Grader:** Model-based rubric.

**Metric:** Average per-criterion coverage score > 0.80

---

### 3.3 Mutation Testing (Bug Catch Rate)

**What:** If the pipeline code contains a known bug, do the generated tests catch it? This is the most important TestAgent eval.

**How:** Take correct generated pipeline code and inject known mutations:
- Wrong column name in a filter
- Wrong aggregation function (`sum` → `count`)
- Missing a required join key
- Off-by-one in a date filter

Run the generated test suite against each mutated version. Score = (mutations caught) / (total mutations injected).

**Grader:** Code-based — pytest exit code non-zero means mutation caught.

**Metric:** Mutation score > 80%

---

### 3.4 Test Determinism (No Flaky Tests)

**What:** Do the generated tests produce the same pass/fail result across 3 independent runs with the same code?

**How:** Run the same test suite 3 times. Flag any test that flips between pass and fail.

**Grader:** Code-based.

**Metric:** Zero flaky tests across all 3 runs (pass^3 = 100%)

---

### 3.5 Coverage Percentage Calibration

**What:** Does the `coverage_pct` reported by the TestAgent match an independently-measured coverage figure?

**How:** Run `pytest --cov` independently and compare the reported value to `test_results.coverage_pct`.

**Grader:** Code-based — tolerance ±5 percentage points.

**Metric:** 100% of trials within tolerance

---

## Eval 4 — PRAgent

### 4.1 Commit Message Quality

**What:** Does the generated commit message follow the format: single line, < 72 characters, imperative mood, descriptive of the change?

**Grader:** Code-based (length, single-line check) + model-based rubric (imperative mood, descriptiveness).

**Metric:** pass^3 = 100% on structural rules; average rubric score > 4/5

---

### 4.2 PR Body Completeness

**What:** Does the PR body include all required sections: story title, pipeline description, test summary (pass rate and coverage), and link to the GitHub issue?

**How:** Parse the PR body for required sections using regex.

**Grader:** Code-based.

**Metric:** pass^3 = 100%

---

### 4.3 File Placement Correctness

**What:** Are all three committed files placed at the correct repository paths?

Expected paths:
- `src/generated_pipelines/{pipeline_name}.py`
- `tests/generated_tests/test_{pipeline_name}.py`
- `src/generated_pipelines/{pipeline_name}_README.md`

**Grader:** Code-based — verify `files_dict` keys in the commit payload.

**Metric:** pass^3 = 100%

---

### 4.4 Branch Naming Convention

**What:** Does the created branch follow the `etl-agent/{story_id}-{pipeline_name}` naming convention?

**Grader:** Code-based — regex match.

**Metric:** pass^3 = 100%

---

### 4.5 GitHub API Retry Success Rate

**What:** When a transient `GithubException` is injected on the first attempt, does the `react_tool_loop` recover and succeed?

**Grader:** Code-based — inject mock exception on attempt 1, assert final status is not FAILED.

**Metric:** pass@3 = 100%

---

## Eval 5 — DeployAgent

### 5.1 Wheel Buildability

**What:** Does the generated `.whl` package build without errors?

**Grader:** Code-based — verify `bdist_wheel` subprocess exits with code 0.

**Metric:** pass^3 = 100%

---

### 5.2 S3 Upload Integrity

**What:** Does the file uploaded to S3 match the local file exactly?

**How:** Compute SHA-256 of the local `.whl` before upload. After upload, fetch the S3 object's ETag and compare.

**Grader:** Code-based — checksums must match.

**Metric:** pass^3 = 100%

---

### 5.3 Artifact Key Naming Convention

**What:** Does the S3 key follow the expected pattern `pipelines/{pipeline_name}/{run_id}/`?

**Grader:** Code-based — regex match on `s3_artifact_url`.

**Metric:** pass^3 = 100%

---

### 5.4 Non-Blocking Failure Behaviour

**What:** If S3 is unreachable, does the pipeline still reach `DONE` rather than `FAILED`? (DeployAgent is designed to be non-blocking.)

**How:** Inject a mock `S3UploadError`. Assert that `GraphState.status == DONE` despite the error.

**Grader:** Code-based.

**Metric:** pass^3 = 100%

---

## Eval 6 — End-to-End Pipeline

These are the highest-value evals. They test the full chain from natural-language story to GitHub PR.

### 6.1 Full Pipeline Completion Rate

**What:** Given a representative set of 20 realistic Olist stories, what percentage reach `DONE` without manual intervention?

**How:** Build a golden story set covering: simple filter, aggregation, multi-table join, join + aggregate, time-series calculation, deduplication, enrichment. Run each story 3 times.

**Grader:** Code-based — `RunStatus == DONE`.

**Metric:** pass^3 > 85% across the golden set

---

### 6.2 Retry Loop Effectiveness

**What:** In what percentage of full runs does the pipeline succeed *after* at least one coding retry? This measures whether the feedback loop between TestAgent and CodingAgent is working.

**Grader:** Code-based — `retry_count > 0 AND status == DONE`.

**Metric:** Tracked as a dashboard metric; target > 60% of retry runs eventually succeed

---

### 6.3 Stage Latency Budget

**What:** How long does each pipeline node take? Are there regressions after model version upgrades?

**How:** Record wall-clock timestamps at the entry and exit of each node. Track P50 and P95 latency per node.

**Grader:** Code-based — alert if any node's P95 latency increases > 30% vs. baseline.

**Expected baselines (approximate):**

| Node | Expected P50 | Alert threshold |
|---|---|---|
| parse_story | 15s | > 30s |
| resolve_catalog | 2s | > 10s |
| generate_code | 25s | > 60s |
| run_tests | 60s | > 180s |
| create_pr | 10s | > 30s |
| deploy | 20s | > 60s |

---

### 6.4 Token Budget Consumption by Story Complexity

**What:** What fraction of `MAX_TOKENS_PER_RUN` (500,000) is consumed per story category?

**How:** Tag golden stories as simple / medium / complex. Record `RunTokenTracker.budget_pct()` at pipeline end.

**Grader:** Code-based — tracked metric, not a pass/fail gate.

**Goal:** Simple stories < 20% budget; complex stories < 60% budget

---

### 6.5 Dry-Run vs Full-Run Code Equivalence

**What:** For the same story, is the code generated in `dry_run=True` mode semantically equivalent to the code generated in a full run?

**How:** Run the same story in both modes. Pass both generated scripts to an LLM evaluator that scores semantic equivalence.

**Grader:** Model-based — binary match on business logic; 0.0 = different logic, 1.0 = equivalent.

**Metric:** Average score > 0.90

---

### 6.6 Approval Gate Precision

**What:** For stories tagged `confidential` or `restricted`, does the approval gate always fire? For `public` or `internal` stories under token budget, does it never fire?

**Grader:** Code-based — binary, zero tolerance.

**Metric:** pass^3 = 100% in both directions

---

## Eval 7 — API & Infrastructure

### 7.1 Input Validation Robustness

**What:** Do malformed story submissions return the correct 422 Unprocessable Entity response?

**Test cases:**
- Empty title (`""`)
- Title > 256 characters
- Description > 2000 characters
- More than 20 acceptance criteria
- Acceptance criterion > 500 characters
- Missing required fields

**Grader:** Code-based — assert HTTP 422 for each case.

**Metric:** 100% of invalid inputs correctly rejected

---

### 7.2 Authentication Enforcement

**What:** Do unauthenticated requests (missing cookie and header) receive HTTP 401? Do requests with a wrong key also receive 401?

**Test cases:**
- No `etl_session` cookie, no `X-API-Key` header
- Wrong `X-API-Key` value
- Expired or tampered cookie value

**Grader:** Code-based.

**Metric:** 100%

---

### 7.3 Run Idempotency

**What:** Does submitting the same story twice create two independent run records with different `run_id` values?

**Grader:** Code-based — assert two distinct `run_id`s in the database.

**Metric:** pass^1 = 100%

---

### 7.4 Concurrent Run Isolation

**What:** Do two simultaneous pipeline runs avoid interfering with each other's database state or token tracking?

**How:** Submit two stories at the same time. Verify that each run's `status`, `retry_count`, `token_tracker`, and `error_message` reflect only that run's activity.

**Grader:** Code-based.

**Metric:** pass^3 = 100%

---

## CI / CD Eval Strategy

Per the Anthropic recommendation: "run on each agent change and model upgrade."

### Fast Suite (runs on every PR, < 2 minutes)

- All code-based graders using **mocked LLM responses**
- Syntax validity (StoryParser, CodingAgent, TestAgent)
- API input validation
- Approval gate routing logic
- Branch naming, file placement, PR body structure
- Non-blocking deploy failure behaviour

### Slow Suite (runs nightly or on model version bump, 10–30 minutes)

- Live LLM calls on the 20 golden stories
- ETLSpec field accuracy
- Acceptance criteria coverage (model-based)
- PySpark runtime correctness
- Full pipeline completion rate
- Stage latency baseline check

### Weekly Suite

- Mutation testing on TestAgent (most expensive, highest signal)
- Token budget consumption tracking
- Dry-run vs full-run equivalence

---

## Priority Order for Implementation

Implement in this order — highest failure impact first:

1. **ETLSpec hallucination check** (Eval 1.3) — wrong columns corrupt all downstream code
2. **Full pipeline completion rate on golden stories** (Eval 6.1) — the system's headline metric
3. **Mutation testing on TestAgent** (Eval 3.3) — tests that don't catch bugs are worthless
4. **PySpark runtime correctness** (Eval 2.2) — syntax passing is not enough
5. **Schema grounding** (Eval 2.3) — prevents hallucinated column references reaching GitHub
6. **Approval gate precision** (Eval 6.6) — compliance-critical, zero tolerance
7. **Retry improvement rate** (Eval 2.6 + 6.2) — validates the self-correction feedback loop
8. All remaining code-based graders (fast to implement, run in CI)

---

## Golden Story Dataset (Seed Set)

The following 10 story types should be in the initial golden set, covering the breadth of Olist ETL operations:

| # | Story Description | Expected Operations | Complexity |
|---|---|---|---|
| 1 | Monthly revenue by seller state | AGGREGATE, JOIN | Simple |
| 2 | Orders delivered late vs on-time | FILTER, AGGREGATE | Simple |
| 3 | Top 10 product categories by review score | JOIN, AGGREGATE, SORT | Medium |
| 4 | Customer RFM segmentation | JOIN, AGGREGATE, ENRICH | Complex |
| 5 | Freight cost outlier detection | FILTER, AGGREGATE | Medium |
| 6 | Seller performance scorecard | JOIN, AGGREGATE, DEDUPE | Complex |
| 7 | Payment method distribution by region | JOIN, AGGREGATE | Medium |
| 8 | Order funnel drop-off analysis | FILTER, AGGREGATE | Medium |
| 9 | Product category translation enrichment | JOIN, ENRICH | Simple |
| 10 | Daily order volume time-series | AGGREGATE, CAST | Simple |
