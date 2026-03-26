"""Spark session management."""


def get_spark_session(app_name: str):
    """Get or create a Spark session."""
    from pyspark.sql import SparkSession
    return SparkSession.builder.appName(app_name).getOrCreate()
