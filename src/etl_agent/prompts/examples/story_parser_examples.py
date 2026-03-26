"""Few-shot examples for the Story Parser Agent prompt."""

STORY_PARSER_EXAMPLES = [
    {
        "input": """id: story-001
title: Clean nulls in customer data
description: Remove rows with null customer_id from the customer table.
source:
  path: s3://etl-raw/customers/
  format: parquet
target:
  path: s3://etl-processed/customers_clean/
  format: delta
transformations:
  - operation: filter
    description: Remove null customer_ids
    config:
      condition: customer_id IS NOT NULL""",
        "output": """{
  "story_id": "story-001",
  "pipeline_name": "clean_nulls_pipeline",
  "description": "Filter null customer_ids from the customer table.",
  "operations": ["filter"],
  "source": {
    "path": "s3://etl-raw/customers/",
    "format": "parquet"
  },
  "target": {
    "path": "s3://etl-processed/customers_clean/",
    "format": "delta"
  },
  "transformations": [
    {
      "operation": "filter",
      "description": "Remove rows where customer_id is null",
      "config": {"condition": "customer_id IS NOT NULL"}
    }
  ],
  "delta_operation": "overwrite",
  "requires_broadcast_join": false,
  "partition_columns": [],
  "estimated_complexity": "low"
}""",
    },
    {
        "input": """id: story-004
title: Score customers using RFM analysis
description: Compute Recency, Frequency, and Monetary scores per customer using quintile bucketing.
source:
  path: s3://etl-agent-raw/amazon_orders.parquet
  format: parquet
target:
  path: s3://etl-agent-processed/rfm_scores
  format: delta
transformations:
  - operation: aggregate
    description: Compute recency days, order count, total spend per customer
    config:
      group_by: [customer_id]
      metrics: [recency_days, order_count, total_spend]
  - operation: enrich
    description: Add R, F, M quintile scores and rfm_segment label
    config:
      derived_columns: [r_score, f_score, m_score, rfm_score, rfm_segment]""",
        "output": """{
  "story_id": "story-004",
  "pipeline_name": "rfm_analysis_pipeline",
  "description": "Compute RFM scores per customer using quintile bucketing.",
  "operations": ["aggregate", "enrich"],
  "source": {
    "path": "s3://etl-agent-raw/amazon_orders.parquet",
    "format": "parquet"
  },
  "target": {
    "path": "s3://etl-agent-processed/rfm_scores",
    "format": "delta"
  },
  "transformations": [
    {
      "operation": "aggregate",
      "description": "Group by customer_id and compute recency_days, frequency, monetary",
      "config": {
        "group_by": ["customer_id"],
        "aggregations": [
          {"function": "datediff", "column": "order_date", "alias": "recency_days"},
          {"function": "count", "column": "order_id", "alias": "frequency"},
          {"function": "sum", "column": "order_amount", "alias": "monetary"}
        ]
      }
    },
    {
      "operation": "enrich",
      "description": "Add r_score, f_score, m_score quintiles and rfm_segment label",
      "config": {
        "derived_columns": [
          {"name": "r_score", "expression": "ntile(5) OVER (ORDER BY recency_days DESC)"},
          {"name": "f_score", "expression": "ntile(5) OVER (ORDER BY frequency ASC)"},
          {"name": "m_score", "expression": "ntile(5) OVER (ORDER BY monetary ASC)"},
          {"name": "rfm_score", "expression": "r_score + f_score + m_score"},
          {"name": "rfm_segment", "expression": "CASE WHEN rfm_score >= 13 THEN 'Champions' WHEN rfm_score >= 10 THEN 'Loyal Customers' WHEN rfm_score >= 7 THEN 'Potential Loyalists' WHEN rfm_score >= 4 THEN 'At Risk' ELSE 'Lost' END"}
        ]
      }
    }
  ],
  "delta_operation": "overwrite",
  "requires_broadcast_join": false,
  "partition_columns": [],
  "estimated_complexity": "medium"
}""",
    },
]
