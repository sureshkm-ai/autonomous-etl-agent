"""LLM response caching using LangChain's SQLiteCache (dev) or RedisCache (prod)."""
from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


def configure_llm_cache(use_redis: bool = False, redis_url: str = "redis://localhost:6379/0") -> None:
    """
    Configure LangChain's global LLM cache.

    In dev (use_redis=False): uses SQLiteCache for lightweight local caching.
    In prod (use_redis=True): uses RedisCache for shared distributed caching.
    """
    try:
        from langchain.globals import set_llm_cache  # type: ignore[import]

        if use_redis:
            from langchain_community.cache import RedisCache  # type: ignore[import]
            import redis as redis_client  # type: ignore[import]
            r = redis_client.from_url(redis_url)
            set_llm_cache(RedisCache(redis_=r))
            logger.info("llm_cache_configured", backend="redis", url=redis_url)
        else:
            from langchain_community.cache import SQLiteCache  # type: ignore[import]
            set_llm_cache(SQLiteCache(database_path=".langchain_cache.db"))
            logger.info("llm_cache_configured", backend="sqlite")

    except ImportError:
        logger.warning("llm_cache_unavailable", reason="langchain_community not installed")
