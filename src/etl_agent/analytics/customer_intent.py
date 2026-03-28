"""Customer intent scoring for targeted campaign delivery."""

from __future__ import annotations

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)

# Valid intent segment labels — referenced by unit tests
VALID_INTENT_SEGMENTS = ["High Intent", "Medium Intent", "Low Intent"]


def run_intent_scoring(
    spark_or_orders_path,
    orders_df_or_customers_path=None,
    customers_df_or_output: str | None = None,
    output_path: str | None = None,
    target_category: str = "iPhone 17",
) -> None:
    """
    Score customers by their likelihood to purchase a target product.

    Supports two calling conventions:
      1. run_intent_scoring(orders_path, products_path, output_path)   — path-based
      2. run_intent_scoring(spark, orders_df, customers_df, output_path=…) — DataFrame-based

    Intent score = target_category_purchases × 3 + avg_spend / 1000 + category_diversity
    """
    from pyspark.sql import DataFrame, SparkSession
    from pyspark.sql import functions as F

    # ── Resolve calling convention ────────────────────────────────────────────
    if isinstance(spark_or_orders_path, SparkSession):
        spark = spark_or_orders_path
        orders: DataFrame = orders_df_or_customers_path  # type: ignore[assignment]
        _customers: DataFrame | None = (
            customers_df_or_output if not isinstance(customers_df_or_output, str) else None
        )  # type: ignore[assignment]
        _output = output_path or "/tmp/intent_output"
        if isinstance(customers_df_or_output, str):
            _output = customers_df_or_output
    else:
        from etl_agent.spark.session import get_or_create_spark

        spark = get_or_create_spark("CustomerIntentScoring")
        orders = spark.read.parquet(spark_or_orders_path)
        _customers = (
            spark.read.parquet(orders_df_or_customers_path) if orders_df_or_customers_path else None
        )
        _output = customers_df_or_output or output_path or "/tmp/intent_output"

    logger.info("intent_scoring_started", target_category=target_category)

    # Determine column names
    amount_col = "total_amount" if "total_amount" in orders.columns else "order_amount"
    category_col = None
    for col in ("category", "product_category", "product_family"):
        if col in orders.columns:
            category_col = col
            break

    # ── Compute intent signals ────────────────────────────────────────────────
    agg_exprs = [
        F.avg(amount_col).alias("avg_spend"),
        F.count("order_id").alias("total_orders"),
        F.sum(amount_col).alias("total_spent"),
    ]

    if category_col:
        agg_exprs += [
            F.count(F.when(F.col(category_col).contains(target_category), 1)).alias(
                "target_purchases"
            ),
            F.countDistinct(category_col).alias("category_diversity"),
        ]
    else:
        agg_exprs += [
            F.lit(0).alias("target_purchases"),
            F.lit(1).alias("category_diversity"),
        ]

    intent = orders.groupBy("customer_id").agg(*agg_exprs)

    # ── Scoring ───────────────────────────────────────────────────────────────
    intent = intent.withColumn(
        "intent_score",
        F.least(
            F.lit(100.0),
            F.greatest(
                F.lit(0.0),
                (F.col("target_purchases") * 10.0)
                + (F.col("avg_spend") / 500.0)
                + (F.col("category_diversity") * 2.0)
                + (F.log1p(F.col("total_orders")) * 5.0),
            ),
        ),
    ).withColumn(
        "intent_segment",
        F.when(F.col("intent_score") >= 30, "High Intent")
        .when(F.col("intent_score") >= 10, "Medium Intent")
        .otherwise("Low Intent"),
    )

    intent.write.format("delta").mode("overwrite").save(_output)
    logger.info("intent_scoring_completed", output_path=_output)
