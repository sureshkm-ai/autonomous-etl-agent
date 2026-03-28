"""Geographic revenue analysis for campaign targeting."""

from __future__ import annotations

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


def run_geo_analysis(
    spark_or_orders_path,
    orders_df_or_customers_path=None,
    customers_df_or_output: str | None = None,
    output_path: str | None = None,
    high_value_threshold: float = 10_000.0,
) -> None:
    """
    Aggregate revenue by geography and flag high-value regions.

    Supports two calling conventions:
      1. run_geo_analysis(orders_path, customers_path, output_path)   — path-based
      2. run_geo_analysis(spark, orders_df, customers_df, output_path=…) — DataFrame-based
    """
    from pyspark.sql import DataFrame, SparkSession
    from pyspark.sql import functions as F

    # ── Resolve calling convention ────────────────────────────────────────────
    if isinstance(spark_or_orders_path, SparkSession):
        spark = spark_or_orders_path
        orders: DataFrame = orders_df_or_customers_path  # type: ignore[assignment]
        customers: DataFrame = customers_df_or_output  # type: ignore[assignment]
        _output = output_path or "/tmp/geo_output"
    else:
        from etl_agent.spark.session import get_or_create_spark

        spark = get_or_create_spark("GeoAnalysis")
        orders = spark.read.parquet(spark_or_orders_path)
        customers = spark.read.parquet(orders_df_or_customers_path)
        _output = customers_df_or_output or output_path or "/tmp/geo_output"

    logger.info("geo_analysis_started", output_path=_output)

    # Determine column names flexibly
    amount_col = "total_amount" if "total_amount" in orders.columns else "order_amount"

    joined = orders.join(
        F.broadcast(customers.select("customer_id", "country", "region")),
        on="customer_id",
        how="left",
    )

    geo_revenue = (
        joined.groupBy("country", "region")
        .agg(
            F.sum(amount_col).alias("total_revenue"),
            F.countDistinct("customer_id").alias("unique_customers"),
            F.count("order_id").alias("order_count"),
            F.avg(amount_col).alias("avg_order_value"),
        )
        .withColumn("revenue_per_customer", F.col("total_revenue") / F.col("unique_customers"))
        .withColumn("is_high_value", F.col("total_revenue") > high_value_threshold)
        .orderBy(F.col("total_revenue").desc())
    )

    geo_revenue.write.format("delta").mode("overwrite").save(_output)
    logger.info("geo_analysis_completed", output_path=_output)
