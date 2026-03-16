"""Few-shot examples for the Test Agent prompt."""

TEST_GEN_EXAMPLES = [
    '''import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, IntegerType
import pyspark.sql.functions as F


@pytest.fixture(scope="module")
def spark():
    return SparkSession.builder.master("local[1]").appName("test").getOrCreate()


@pytest.fixture
def sample_df(spark):
    data = [("CUST-001", "alice@example.com", "US"),
            ("CUST-002", None, "GB"),
            (None, "bob@example.com", "DE")]
    return spark.createDataFrame(data, ["customer_id", "email", "country"])


def test_schema_has_required_columns(sample_df):
    """Schema must include customer_id, email, country."""
    required = {"customer_id", "email", "country"}
    assert required.issubset(set(sample_df.columns))


def test_filter_removes_null_customer_ids(sample_df):
    """After filter, no null customer_ids should remain."""
    result = sample_df.filter(F.col("customer_id").isNotNull())
    null_count = result.filter(F.col("customer_id").isNull()).count()
    assert null_count == 0


def test_output_row_count_is_less_than_input(sample_df):
    """Filtered output must have fewer rows than input."""
    result = sample_df.filter(F.col("customer_id").isNotNull())
    assert result.count() < sample_df.count()
''',
]
