"""Few-shot examples for the Coding Agent prompt."""

CODE_GEN_EXAMPLES = [
    {
        "spec": "filter null customer_ids, write to delta",
        "code": '''"""clean_nulls_pipeline: Remove null customer_ids."""
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from delta import configure_spark_with_delta_pip


def run() -> None:
    """Execute the clean nulls pipeline."""
    spark = (
        configure_spark_with_delta_pip(
            SparkSession.builder.appName("clean_nulls_pipeline")
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog",
                    "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        ).getOrCreate()
    )

    print("Reading source data...")
    df = spark.read.parquet("s3://etl-agent-raw/amazon_customers.parquet")
    print(f"Source rows: {df.count()}")

    print("Applying filter: remove null customer_id...")
    df_clean = df.filter(F.col("customer_id").isNotNull())
    print(f"Output rows: {df_clean.count()}")

    print("Writing to Delta Lake...")
    df_clean.write.format("delta").mode("overwrite").save(
        "s3://etl-agent-processed/customers_clean"
    )
    print("Pipeline complete.")
    spark.stop()


if __name__ == "__main__":
    run()
''',
    }
]
