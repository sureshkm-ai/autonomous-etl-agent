"""Campaign performance optimisation — iPhone 17 campaign ETL."""

from __future__ import annotations

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


def run_campaign_analysis(
    spark_or_campaigns_path,
    campaigns_df_or_orders_path=None,
    orders_df_or_output: str | None = None,
    output_path: str | None = None,
    product_filter: str = "iPhone 17",
) -> None:
    """
    Compute campaign KPIs: conversion_rate, revenue_per_impression, roi_pct, campaign_grade.
    Filters to campaigns matching product_filter (default: 'iPhone 17').

    Supports two calling conventions:
      1. run_campaign_analysis(campaigns_path, orders_path, output_path)  — path-based
      2. run_campaign_analysis(spark, campaigns_df, output_path=…)        — DataFrame-based
    """
    from pyspark.sql import DataFrame, SparkSession
    from pyspark.sql import functions as F

    # ── Resolve calling convention ────────────────────────────────────────────
    if isinstance(spark_or_campaigns_path, SparkSession):
        spark = spark_or_campaigns_path
        campaigns: DataFrame = campaigns_df_or_orders_path  # type: ignore[assignment]
        # In DataFrame mode the second arg IS the campaigns_df; no separate orders_df needed
        _output = orders_df_or_output or output_path or "/tmp/campaign_output"
        # No separate orders DataFrame — KPIs derived purely from campaigns fixture
        orders = None
    else:
        from etl_agent.spark.session import get_or_create_spark

        spark = get_or_create_spark("CampaignOptimizer")
        campaigns = spark.read.parquet(spark_or_campaigns_path)
        orders_path_str = campaigns_df_or_orders_path
        _output = orders_df_or_output or output_path or "/tmp/campaign_output"
        orders = spark.read.parquet(orders_path_str) if orders_path_str else None

    logger.info("campaign_analysis_started", product_filter=product_filter)

    # Filter to target product family
    campaigns_filtered = campaigns.filter(F.col("product_family").contains(product_filter))

    # KPIs — computed directly from impressions/clicks/conversions/revenue/spend columns
    # (Fixture schema: campaign_id, campaign_name, product_family, impressions, clicks,
    #  conversions, revenue, spend)
    if orders is not None:
        # Path-based: join with orders for revenue
        amount_col = "total_amount" if "total_amount" in orders.columns else "order_amount"
        order_agg = (
            orders.filter(F.col("product_family").contains(product_filter))
            .groupBy("campaign_id")
            .agg(
                F.count("order_id").alias("order_count"),
                F.sum(amount_col).alias("total_revenue"),
            )
        )
        base = campaigns_filtered.join(order_agg, on="campaign_id", how="left").fillna(0)
        revenue_col = "total_revenue"
        cost_col = "spend" if "spend" in base.columns else "campaign_cost"
    else:
        # DataFrame-based: use revenue/spend columns directly from fixture
        base = campaigns_filtered.fillna(0)
        revenue_col = "revenue"
        cost_col = "spend"

    performance = (
        base.withColumn(
            "conversion_rate",
            F.when(F.col("impressions") > 0, F.col("conversions") / F.col("impressions")).otherwise(
                0.0
            ),
        )
        .withColumn(
            "revenue_per_impression",
            F.when(F.col("impressions") > 0, F.col(revenue_col) / F.col("impressions")).otherwise(
                0.0
            ),
        )
        .withColumn(
            "roi_pct",
            F.when(
                F.col(cost_col) > 0, (F.col(revenue_col) - F.col(cost_col)) / F.col(cost_col) * 100
            ).otherwise(0.0),
        )
        .withColumn(
            "campaign_grade",
            F.when(F.col("roi_pct") >= 2000, "A")
            .when(F.col("roi_pct") >= 1000, "B")
            .when(F.col("roi_pct") >= 0, "C")
            .otherwise("D"),
        )
    )

    performance.write.format("delta").mode("overwrite").save(_output)
    logger.info("campaign_analysis_completed", output_path=_output)
