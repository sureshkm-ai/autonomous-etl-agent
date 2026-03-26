"""Spark query optimization utilities: broadcast hints, caching, and partition tuning."""
from __future__ import annotations

import math

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)

# Default broadcast threshold (10 MB) — matches framework_config.yaml
_BROADCAST_THRESHOLD_MB: int = 10
_BYTES_PER_MB: int = 1024 * 1024


# ─── Broadcast Hints ─────────────────────────────────────────────────────────


def apply_broadcast_hint(df: DataFrame, threshold_mb: int = _BROADCAST_THRESHOLD_MB) -> DataFrame:
    """
    Apply a broadcast hint to a DataFrame if its estimated size is below the threshold.

    Broadcast joins eliminate shuffle when one side is small, dramatically
    improving join performance at scale.

    Args:
        df: The DataFrame to potentially broadcast.
        threshold_mb: Size threshold in MB (default: 10 MB).

    Returns:
        DataFrame with broadcast hint if small, otherwise unchanged.
    """
    try:
        # Use Spark's query plan statistics if available
        stats = df._jdf.queryExecution().analyzed().stats()
        size_bytes = stats.sizeInBytes()
        size_mb = size_bytes / _BYTES_PER_MB
        if size_mb <= threshold_mb:
            logger.info(
                "applying_broadcast_hint",
                size_mb=round(size_mb, 2),
                threshold_mb=threshold_mb,
            )
            return F.broadcast(df)
        logger.debug(
            "skipping_broadcast_hint",
            size_mb=round(size_mb, 2),
            threshold_mb=threshold_mb,
        )
    except Exception as exc:
        # Statistics unavailable — skip hint silently
        logger.debug("broadcast_hint_stats_unavailable", error=str(exc))
    return df


def broadcast_join(
    left: DataFrame,
    right: DataFrame,
    join_keys: list[str],
    join_type: str = "inner",
    threshold_mb: int = _BROADCAST_THRESHOLD_MB,
) -> DataFrame:
    """
    Perform a join with an automatic broadcast hint on the smaller side.

    Args:
        left: Left DataFrame.
        right: Right DataFrame.
        join_keys: Column name(s) to join on.
        join_type: Spark join type (inner, left, right, full, etc.).
        threshold_mb: Broadcast threshold in MB.

    Returns:
        Joined DataFrame.
    """
    right_broadcast = apply_broadcast_hint(right, threshold_mb)
    return left.join(right_broadcast, on=join_keys, how=join_type)


# ─── Caching ─────────────────────────────────────────────────────────────────


def cache_if_reused(df: DataFrame, name: str | None = None) -> DataFrame:
    """
    Cache a DataFrame and log the action.

    Use this when a DataFrame is read from storage and referenced more than
    once (e.g. once for filtering, once for counting).

    Args:
        df: DataFrame to cache.
        name: Optional label for logging.

    Returns:
        Cached DataFrame.
    """
    logger.info("caching_dataframe", name=name or "unnamed")
    return df.cache()


def unpersist(df: DataFrame, name: str | None = None) -> None:
    """
    Remove a cached DataFrame from memory.

    Args:
        df: Cached DataFrame to unpersist.
        name: Optional label for logging.
    """
    logger.info("unpersisting_dataframe", name=name or "unnamed")
    df.unpersist()


# ─── Partition Optimization ──────────────────────────────────────────────────


def repartition_for_write(
    df: DataFrame,
    target_file_size_mb: int = 128,
    partition_cols: list[str] | None = None,
) -> DataFrame:
    """
    Repartition a DataFrame to produce evenly sized output files.

    Aims for ``target_file_size_mb`` per output file using the estimated
    DataFrame size from Spark's query plan statistics.

    Args:
        df: Input DataFrame.
        target_file_size_mb: Desired output file size in MB (default: 128 MB).
        partition_cols: Optional partition columns (preserves partitioning).

    Returns:
        Repartitioned DataFrame.
    """
    try:
        stats = df._jdf.queryExecution().analyzed().stats()
        total_size_mb = stats.sizeInBytes() / _BYTES_PER_MB
        num_partitions = max(1, math.ceil(total_size_mb / target_file_size_mb))
        logger.info(
            "repartitioning_for_write",
            total_size_mb=round(total_size_mb, 2),
            target_file_size_mb=target_file_size_mb,
            num_partitions=num_partitions,
        )
        if partition_cols:
            return df.repartition(num_partitions, *partition_cols)
        return df.repartition(num_partitions)
    except Exception as exc:
        logger.warning("repartition_stats_unavailable", error=str(exc))
        return df


def coalesce_small_output(df: DataFrame, max_partitions: int = 10) -> DataFrame:
    """
    Coalesce DataFrame partitions to avoid writing many tiny files.

    This is a narrow transformation (no shuffle) and is safe to apply
    before writing small result sets.

    Args:
        df: Input DataFrame.
        max_partitions: Maximum number of output partitions.

    Returns:
        Coalesced DataFrame.
    """
    current = df.rdd.getNumPartitions()
    if current > max_partitions:
        logger.info(
            "coalescing_partitions",
            from_partitions=current,
            to_partitions=max_partitions,
        )
        return df.coalesce(max_partitions)
    return df


# ─── Spark Config Tuning ─────────────────────────────────────────────────────


def configure_adaptive_query_execution(spark: SparkSession) -> None:
    """
    Enable Adaptive Query Execution (AQE) for runtime plan optimization.

    AQE automatically coalesces shuffle partitions, converts sort-merge joins
    to broadcast joins, and optimizes skew joins at runtime.
    """
    spark.conf.set("spark.sql.adaptive.enabled", "true")
    spark.conf.set("spark.sql.adaptive.coalescePartitions.enabled", "true")
    spark.conf.set("spark.sql.adaptive.skewJoin.enabled", "true")
    logger.info("adaptive_query_execution_enabled")


def configure_dynamic_partition_pruning(spark: SparkSession) -> None:
    """
    Enable Dynamic Partition Pruning (DPP) for partition-filtered joins.

    DPP pushes partition filters from a dimension table into a fact table scan,
    reducing I/O significantly for star-schema style queries.
    """
    spark.conf.set("spark.sql.optimizer.dynamicPartitionPruning.enabled", "true")
    logger.info("dynamic_partition_pruning_enabled")


def set_broadcast_threshold(spark: SparkSession, threshold_mb: int = _BROADCAST_THRESHOLD_MB) -> None:
    """
    Set the Spark auto-broadcast threshold.

    Args:
        spark: Active SparkSession.
        threshold_mb: Size in MB below which tables are auto-broadcast.
    """
    threshold_bytes = threshold_mb * _BYTES_PER_MB
    spark.conf.set("spark.sql.autoBroadcastJoinThreshold", str(threshold_bytes))
    logger.info("broadcast_threshold_set", threshold_mb=threshold_mb)


def apply_all_optimizations(spark: SparkSession, broadcast_threshold_mb: int = _BROADCAST_THRESHOLD_MB) -> None:
    """
    Apply the full recommended set of Spark optimizations in one call.

    Should be called once after SparkSession creation, before running
    any pipeline logic.

    Args:
        spark: Active SparkSession.
        broadcast_threshold_mb: Auto-broadcast threshold in MB.
    """
    configure_adaptive_query_execution(spark)
    configure_dynamic_partition_pruning(spark)
    set_broadcast_threshold(spark, broadcast_threshold_mb)
    logger.info("all_spark_optimizations_applied", broadcast_threshold_mb=broadcast_threshold_mb)
