"""Few-shot examples for the Story Parser Agent prompt."""

STORY_PARSER_EXAMPLES = [
    {
        "input": """id: story-001
title: Clean nulls in customer data
transformations:
  - operation: filter
    column: customer_id
    condition: is_not_null""",
        "output": """{
  "story_id": "story-001",
  "pipeline_name": "clean_nulls_pipeline",
  "description": "Filter null customer_ids from the customer table.",
  "operations": ["filter"],
  "delta_operation": "overwrite",
  "requires_broadcast_join": false,
  "partition_columns": [],
  "estimated_complexity": "low"
}""",
    },
    {
        "input": """id: story-004
title: Score customers using RFM analysis
transformations:
  - operation: aggregate
    group_by: [customer_id]
    metrics: [recency_days, order_count, total_spend]
  - operation: enrich
    column: rfm_score""",
        "output": """{
  "story_id": "story-004",
  "pipeline_name": "rfm_analysis_pipeline",
  "description": "Compute RFM scores per customer using quintile bucketing.",
  "operations": ["aggregate", "enrich"],
  "delta_operation": "merge",
  "requires_broadcast_join": false,
  "partition_columns": [],
  "estimated_complexity": "medium"
}""",
    },
]
