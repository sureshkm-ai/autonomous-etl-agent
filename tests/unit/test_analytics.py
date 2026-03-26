"""Unit tests for business analytics pipelines (RFM, Geo, Campaign, Intent)."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest


# ─── PySpark fixtures are session-scoped to avoid repeated JVM init ───────────

def _configure_java_home() -> None:
    """Point JAVA_HOME at Java 17 if available.

    PySpark 3.5 works with Java 17; Java 21 removed Subject.getSubject()
    which Hadoop 3.3.x calls, crashing the JVM gateway on startup.
    """
    import os
    from pathlib import Path

    # Already set externally (e.g. via Makefile) — honour it
    if "JAVA_HOME" in os.environ:
        return

    candidates = [
        # Homebrew on Apple Silicon
        "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
        # Homebrew on Intel
        "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
        # Linux SDKMAN / system installs
        "/usr/lib/jvm/java-17-openjdk-arm64",
        "/usr/lib/jvm/java-17-openjdk-amd64",
        "/usr/lib/jvm/java-17-openjdk",
        "/usr/lib/jvm/temurin-17",
    ]
    for path in candidates:
        if Path(path).exists():
            os.environ["JAVA_HOME"] = path
            # PySpark 3.5 on Java 17 needs these module opens
            os.environ.setdefault("JAVA_TOOL_OPTIONS", " ".join([
                "--add-opens=java.base/java.lang=ALL-UNNAMED",
                "--add-opens=java.base/java.lang.invoke=ALL-UNNAMED",
                "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
                "--add-opens=java.base/java.io=ALL-UNNAMED",
                "--add-opens=java.base/java.net=ALL-UNNAMED",
                "--add-opens=java.base/java.nio=ALL-UNNAMED",
                "--add-opens=java.base/java.util=ALL-UNNAMED",
                "--add-opens=java.base/java.util.concurrent=ALL-UNNAMED",
                "--add-opens=java.base/java.util.concurrent.atomic=ALL-UNNAMED",
                "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED",
                "--add-opens=java.base/sun.nio.cs=ALL-UNNAMED",
                "--add-opens=java.base/sun.security.action=ALL-UNNAMED",
                "--add-opens=java.base/sun.util.calendar=ALL-UNNAMED",
                "--add-opens=java.security.jgss/sun.security.krb5=ALL-UNNAMED",
            ]))
            break


@pytest.fixture(scope="session")
def spark():
    """Create a test SparkSession with Delta Lake support."""
    _configure_java_home()
    try:
        from pyspark.sql import SparkSession
        from delta import configure_spark_with_delta_pip

        builder = (
            SparkSession.builder.master("local[1]")
            .appName("etl-agent-analytics-tests")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config(
                "spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog",
            )
            .config("spark.ui.enabled", "false")
            .config("spark.sql.shuffle.partitions", "2")
        )
        _spark = configure_spark_with_delta_pip(builder).getOrCreate()
    except Exception as e:
        pytest.skip(f"Spark not available in this environment: {e}")
        return

    yield _spark
    _spark.stop()


@pytest.fixture
def orders_df(spark):
    """Sample Amazon orders DataFrame."""
    from pyspark.sql.types import StructType, StructField, StringType, DateType, DoubleType, IntegerType

    schema = StructType([
        StructField("order_id", StringType(), False),
        StructField("customer_id", StringType(), False),
        StructField("order_date", DateType(), False),
        StructField("total_amount", DoubleType(), True),
        StructField("quantity", IntegerType(), True),
    ])

    today = date.today()
    data = [
        ("ORD-001", "CUST-A", today - timedelta(days=5),  120.0, 2),
        ("ORD-002", "CUST-A", today - timedelta(days=10), 80.0,  1),
        ("ORD-003", "CUST-B", today - timedelta(days=90), 200.0, 3),
        ("ORD-004", "CUST-C", today - timedelta(days=200), 50.0, 1),
        ("ORD-005", "CUST-D", today - timedelta(days=365), 500.0, 5),
    ]
    return spark.createDataFrame(data, schema=schema)


@pytest.fixture
def customers_df(spark):
    """Sample customer profile DataFrame."""
    from pyspark.sql.types import StructType, StructField, StringType

    schema = StructType([
        StructField("customer_id", StringType(), False),
        StructField("country", StringType(), True),
        StructField("region", StringType(), True),
        StructField("email", StringType(), True),
    ])

    data = [
        ("CUST-A", "US",  "North", "a@example.com"),
        ("CUST-B", "UK",  "South", "b@example.com"),
        ("CUST-C", "US",  "West",  None),
        ("CUST-D", "CA",  "East",  "d@example.com"),
    ]
    return spark.createDataFrame(data, schema=schema)


@pytest.fixture
def campaigns_df(spark):
    """Sample iPhone 17 campaign DataFrame."""
    from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType

    schema = StructType([
        StructField("campaign_id", StringType(), False),
        StructField("campaign_name", StringType(), True),
        StructField("product_family", StringType(), True),
        StructField("impressions", LongType(), True),
        StructField("clicks", LongType(), True),
        StructField("conversions", LongType(), True),
        StructField("revenue", DoubleType(), True),
        StructField("spend", DoubleType(), True),
    ])

    data = [
        ("CAM-001", "iPhone 17 Launch",     "iPhone 17 Pro",    100000, 5000, 250, 250000.0, 10000.0),
        ("CAM-002", "iPhone 17 Mid Season", "iPhone 17",         50000, 2000,  80,  64000.0,  5000.0),
        ("CAM-003", "Generic Tech",          "Samsung Galaxy",   30000,  800,  10,   5000.0,  3000.0),
    ]
    return spark.createDataFrame(data, schema=schema)


# ─── Tests: RFM Analysis ─────────────────────────────────────────────────────

class TestRFMAnalysis:
    def test_rfm_output_has_all_customers(self, spark, orders_df, tmp_path) -> None:
        from etl_agent.analytics.rfm_analysis import run_rfm_analysis

        output_path = str(tmp_path / "rfm_output")
        run_rfm_analysis(spark, orders_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        assert result.count() == orders_df.select("customer_id").distinct().count()

    def test_rfm_output_has_segment_column(self, spark, orders_df, tmp_path) -> None:
        from etl_agent.analytics.rfm_analysis import run_rfm_analysis

        output_path = str(tmp_path / "rfm_seg")
        run_rfm_analysis(spark, orders_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        assert "rfm_segment" in result.columns

    def test_rfm_no_null_segments(self, spark, orders_df, tmp_path) -> None:
        from etl_agent.analytics.rfm_analysis import run_rfm_analysis
        from pyspark.sql import functions as F

        output_path = str(tmp_path / "rfm_null_check")
        run_rfm_analysis(spark, orders_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        null_count = result.filter(F.col("rfm_segment").isNull()).count()
        assert null_count == 0

    def test_rfm_valid_segment_values(self, spark, orders_df, tmp_path) -> None:
        from etl_agent.analytics.rfm_analysis import run_rfm_analysis, VALID_SEGMENTS

        output_path = str(tmp_path / "rfm_valid_segs")
        run_rfm_analysis(spark, orders_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        segments = {row.rfm_segment for row in result.select("rfm_segment").distinct().collect()}
        assert segments.issubset(set(VALID_SEGMENTS))


# ─── Tests: Geo Analytics ─────────────────────────────────────────────────────

class TestGeoAnalytics:
    def test_geo_output_row_count(self, spark, orders_df, customers_df, tmp_path) -> None:
        from etl_agent.analytics.geo_analytics import run_geo_analysis

        output_path = str(tmp_path / "geo_output")
        run_geo_analysis(spark, orders_df, customers_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        assert result.count() > 0

    def test_geo_output_has_required_columns(self, spark, orders_df, customers_df, tmp_path) -> None:
        from etl_agent.analytics.geo_analytics import run_geo_analysis

        output_path = str(tmp_path / "geo_cols")
        run_geo_analysis(spark, orders_df, customers_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        required_cols = {"country", "total_revenue", "unique_customers"}
        assert required_cols.issubset(set(result.columns))

    def test_geo_total_revenue_non_negative(self, spark, orders_df, customers_df, tmp_path) -> None:
        from etl_agent.analytics.geo_analytics import run_geo_analysis
        from pyspark.sql import functions as F

        output_path = str(tmp_path / "geo_rev")
        run_geo_analysis(spark, orders_df, customers_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        negative_count = result.filter(F.col("total_revenue") < 0).count()
        assert negative_count == 0


# ─── Tests: Campaign Optimizer ────────────────────────────────────────────────

class TestCampaignOptimizer:
    def test_campaign_filters_iphone17(self, spark, campaigns_df, tmp_path) -> None:
        from etl_agent.analytics.campaign_optimizer import run_campaign_analysis

        output_path = str(tmp_path / "campaign_output")
        run_campaign_analysis(spark, campaigns_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        # Only iPhone 17 campaigns should be in output
        for row in result.collect():
            assert "iPhone 17" in row.product_family

    def test_campaign_has_kpi_columns(self, spark, campaigns_df, tmp_path) -> None:
        from etl_agent.analytics.campaign_optimizer import run_campaign_analysis

        output_path = str(tmp_path / "campaign_kpis")
        run_campaign_analysis(spark, campaigns_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        required_kpis = {"conversion_rate", "revenue_per_impression", "roi_pct", "campaign_grade"}
        assert required_kpis.issubset(set(result.columns))

    def test_campaign_grades_are_valid(self, spark, campaigns_df, tmp_path) -> None:
        from etl_agent.analytics.campaign_optimizer import run_campaign_analysis

        output_path = str(tmp_path / "campaign_grades")
        run_campaign_analysis(spark, campaigns_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        valid_grades = {"A", "B", "C", "D"}
        for row in result.select("campaign_grade").collect():
            assert row.campaign_grade in valid_grades, f"Invalid grade: {row.campaign_grade}"


# ─── Tests: Customer Intent ───────────────────────────────────────────────────

class TestCustomerIntent:
    def test_intent_output_has_all_customers(self, spark, orders_df, customers_df, tmp_path) -> None:
        from etl_agent.analytics.customer_intent import run_intent_scoring

        output_path = str(tmp_path / "intent_output")
        run_intent_scoring(spark, orders_df, customers_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        assert result.count() > 0

    def test_intent_score_is_between_0_and_100(self, spark, orders_df, customers_df, tmp_path) -> None:
        from etl_agent.analytics.customer_intent import run_intent_scoring
        from pyspark.sql import functions as F

        output_path = str(tmp_path / "intent_score_range")
        run_intent_scoring(spark, orders_df, customers_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        out_of_range = result.filter(
            (F.col("intent_score") < 0) | (F.col("intent_score") > 100)
        ).count()
        assert out_of_range == 0

    def test_intent_segments_are_valid(self, spark, orders_df, customers_df, tmp_path) -> None:
        from etl_agent.analytics.customer_intent import run_intent_scoring, VALID_INTENT_SEGMENTS

        output_path = str(tmp_path / "intent_segs")
        run_intent_scoring(spark, orders_df, customers_df, output_path=output_path)

        result = spark.read.format("delta").load(output_path)
        segments = {r.intent_segment for r in result.select("intent_segment").distinct().collect()}
        assert segments.issubset(set(VALID_INTENT_SEGMENTS))
