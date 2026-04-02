"""Few-shot examples for the Story Parser Agent prompt.

Both examples use Olist Brazilian E-Commerce entities from the Glue catalog,
showing the LLM how to resolve S3 paths and column names from catalog context.
"""

STORY_PARSER_EXAMPLES = [
    {
        "input": """Title: Monthly Revenue by Product Category
Description: Aggregate the total payment value per product category per month,
joining orders with order_items, payments, and products.
Acceptance Criteria:
  - Output contains columns: year, month, product_category_name, total_revenue
  - Only include orders with status = 'delivered'
  - Partition output by year and month

Available catalog entities (excerpt):
  - orders | s3://etl-agent-raw-production/olist/orders/ | csv
    columns: order_id (string), customer_id (string), order_status (string),
             order_purchase_timestamp (string)
  - order_payments | s3://etl-agent-raw-production/olist/order_payments/ | csv
    columns: order_id (string), payment_sequential (int), payment_type (string),
             payment_value (double)
  - order_items | s3://etl-agent-raw-production/olist/order_items/ | csv
    columns: order_id (string), product_id (string), price (double), freight_value (double)
  - products | s3://etl-agent-raw-production/olist/products/ | csv
    columns: product_id (string), product_category_name (string)

Output bucket: s3://etl-agent-processed-production/""",
        "output": """{
  "story_id": "auto-generated",
  "pipeline_name": "monthly_revenue_by_product_category",
  "description": "Aggregate total payment value per product category per month for delivered orders.",
  "operations": ["filter", "join", "aggregate"],
  "source": {
    "path": "s3://etl-agent-raw-production/olist/orders/",
    "format": "csv"
  },
  "target": {
    "path": "s3://etl-agent-processed-production/monthly_revenue_by_product_category/",
    "format": "csv"
  },
  "transformations": [
    {
      "operation": "filter",
      "description": "Keep only orders with order_status = 'delivered'",
      "config": {"condition": "order_status = 'delivered'"}
    },
    {
      "operation": "join",
      "description": "Join orders with order_payments on order_id",
      "config": {
        "right_path": "s3://etl-agent-raw-production/olist/order_payments/",
        "join_type": "inner",
        "on": "order_id"
      }
    },
    {
      "operation": "join",
      "description": "Join with order_items on order_id to get product_id",
      "config": {
        "right_path": "s3://etl-agent-raw-production/olist/order_items/",
        "join_type": "inner",
        "on": "order_id"
      }
    },
    {
      "operation": "join",
      "description": "Join with products on product_id to get product_category_name",
      "config": {
        "right_path": "s3://etl-agent-raw-production/olist/products/",
        "join_type": "left",
        "on": "product_id"
      }
    },
    {
      "operation": "aggregate",
      "description": "Sum payment_value grouped by year, month, product_category_name",
      "config": {
        "group_by": ["year(order_purchase_timestamp)", "month(order_purchase_timestamp)", "product_category_name"],
        "aggregations": [{"function": "sum", "column": "payment_value", "alias": "total_revenue"}]
      }
    }
  ],
  "delta_operation": "overwrite",
  "requires_broadcast_join": true,
  "partition_columns": ["year", "month"],
  "estimated_complexity": "high"
}""",
    },
    {
        "input": """Title: Customer Order Frequency Report
Description: Count the number of delivered orders per customer and classify
them as 'one_time', 'repeat', or 'loyal' based on order frequency.
Acceptance Criteria:
  - Output contains: customer_unique_id, order_count, customer_segment
  - one_time = 1 order, repeat = 2-4 orders, loyal = 5+ orders
  - Only delivered orders

Available catalog entities (excerpt):
  - orders | s3://etl-agent-raw-production/olist/orders/ | csv
    columns: order_id (string), customer_id (string), order_status (string),
             order_purchase_timestamp (string)
  - customers | s3://etl-agent-raw-production/olist/customers/ | csv
    columns: customer_id (string), customer_unique_id (string),
             customer_city (string), customer_state (string)

Output bucket: s3://etl-agent-processed-production/""",
        "output": """{
  "story_id": "auto-generated",
  "pipeline_name": "customer_order_frequency_report",
  "description": "Count delivered orders per customer and classify them into one_time, repeat, or loyal segments.",
  "operations": ["filter", "join", "aggregate", "enrich"],
  "source": {
    "path": "s3://etl-agent-raw-production/olist/orders/",
    "format": "csv"
  },
  "target": {
    "path": "s3://etl-agent-processed-production/customer_order_frequency_report/",
    "format": "csv"
  },
  "transformations": [
    {
      "operation": "filter",
      "description": "Keep only orders with order_status = 'delivered'",
      "config": {"condition": "order_status = 'delivered'"}
    },
    {
      "operation": "join",
      "description": "Join orders with customers on customer_id to get customer_unique_id",
      "config": {
        "right_path": "s3://etl-agent-raw-production/olist/customers/",
        "join_type": "inner",
        "on": "customer_id"
      }
    },
    {
      "operation": "aggregate",
      "description": "Count orders per customer_unique_id",
      "config": {
        "group_by": ["customer_unique_id"],
        "aggregations": [{"function": "count", "column": "order_id", "alias": "order_count"}]
      }
    },
    {
      "operation": "enrich",
      "description": "Add customer_segment column based on order_count",
      "config": {
        "derived_columns": [
          {
            "name": "customer_segment",
            "expression": "CASE WHEN order_count = 1 THEN 'one_time' WHEN order_count <= 4 THEN 'repeat' ELSE 'loyal' END"
          }
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
