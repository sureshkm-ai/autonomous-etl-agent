"""
RFM (Recency, Frequency, Monetary) analysis pipeline.
Scores customers for targeted marketing campaigns (e.g. Amazon iPhone 17 launch).
"""
from __future__ import annotations

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)

# Valid RFM segment labels — referenced by unit tests
VALID_SEGMENTS = ["Champions", "Loyal Customers", "Potential Loyalists", "At Risk", "Lost"]


def run_rfm_analysis(
    spark_or_path,
    orders_df_or_output: str | None = None,
    output_path: str | None = None,
    reference_date: str | None = None,
) -> None:
    """
    Compute RFM scores for all customers.

    Supports two calling conventions:
      1. run_rfm_analysis(orders_path, output_path)        — path-based (CLI/Airflow)
      2. run_rfm_analysis(spark, orders_df, output_path=…) — DataFrame-based (tests/notebooks)

    RFM metrics:
      - Recency : days since last order (lower = better → score 5 = most recent)
      - Frequency: number of orders (higher = better)
      - Monetary : total spend (higher = better)

    Each metric scored 1-5 via quintile bucketing.
    Combined rfm_score = R + F + M (range 3–15).
    """
    from pyspark.sql import SparkSession, DataFrame
    from pyspark.sql import functions as F

    # ── Resolve calling convention ────────────────────────────────────────────
    if isinstance(spark_or_path, SparkSession):
        spark = spark_or_path
        orders_df: DataFrame = orders_df_or_output  # type: ignore[assignment]
        _output_path = output_path or "/tmp/rfm_output"
        _ref_date = reference_date or "2099-01-01"
    else:
        # Path-based: spark_or_path is orders_path string
        from etl_agent.spark.session import get_or_create_spark
        spark = get_or_create_spark("RFMAnalysis")
        orders_df = spark.read.parquet(spark_or_path)
        _output_path = orders_df_or_output or output_path or "/tmp/rfm_output"
        _ref_date = reference_date or "2099-01-01"

    logger.info("rfm_analysis_started", output_path=_output_path)

    # Determine order amount column name
    amount_col = "total_amount" if "total_amount" in orders_df.columns else "order_amount"
    date_col = "order_date" if "order_date" in orders_df.columns else "order_date"

    # ── Compute raw RFM metrics per customer ──────────────────────────────────
    rfm = orders_df.groupBy("customer_id").agg(
        F.datediff(F.current_date(), F.max(date_col)).alias("recency_days"),
        F.count("order_id").alias("frequency"),
        F.sum(amount_col).alias("monetary"),
    )

    # ── Quintile scoring ──────────────────────────────────────────────────────
    def quintile_score(col_name: str, ascending: bool = True) -> F.Column:
        """Bucket column values into quintile scores 1-5."""
        pcts = [0.2, 0.4, 0.6, 0.8]
        try:
            thresholds = rfm.approxQuantile(col_name, pcts, 0.05)
        except Exception:
            thresholds = [0.0, 0.0, 0.0, 0.0]

        expr = F.when(F.col(col_name) <= thresholds[0], 1 if ascending else 5)
        for i, t in enumerate(thresholds[1:], 2):
            expr = expr.when(F.col(col_name) <= t, i if ascending else 6 - i)
        return expr.otherwise(5 if ascending else 1)

    rfm_scored = (
        rfm
        .withColumn("r_score", quintile_score("recency_days", ascending=False))
        .withColumn("f_score", quintile_score("frequency", ascending=True))
        .withColumn("m_score", quintile_score("monetary", ascending=True))
        .withColumn("rfm_score", F.col("r_score") + F.col("f_score") + F.col("m_score"))
        .withColumn(
            "rfm_segment",
            F.when(F.col("rfm_score") >= 13, "Champions")
            .when(F.col("rfm_score") >= 10, "Loyal Customers")
            .when(F.col("rfm_score") >= 7,  "Potential Loyalists")
            .when(F.col("rfm_score") >= 4,  "At Risk")
            .otherwise("Lost"),
        )
    )

    # ── Write to Delta Lake ───────────────────────────────────────────────────
    rfm_scored.write.format("delta").mode("overwrite").option(
        "overwriteSchema", "true"
    ).save(_output_path)

    logger.info(
        "rfm_analysis_completed",
        output_path=_output_path,
        customer_count=rfm_scored.count(),
    )
