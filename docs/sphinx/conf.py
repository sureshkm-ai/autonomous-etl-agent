# Configuration file for the Sphinx documentation builder.
#
# To build:
#   pip install sphinx sphinx-rtd-theme myst-parser
#   cd docs/sphinx && make html
#   open _build/html/index.html

import os
import sys

sys.path.insert(0, os.path.abspath("../../src"))

# ── Project information ────────────────────────────────────────────────────────

project = "Autonomous ETL Agent"
copyright = "2025, Suresh"
author = "Suresh"
release = "1.0.0"

# ── Extensions ────────────────────────────────────────────────────────────────

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
    "sphinxcontrib.mermaid",
]

# Render Mermaid diagrams client-side via JavaScript (no mmdc binary required)
mermaid_output_format = "raw"

# ── Templates / static ────────────────────────────────────────────────────────

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# ── HTML theme ────────────────────────────────────────────────────────────────

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

html_theme_options = {
    "navigation_depth": 4,
    "titles_only": False,
    "collapse_navigation": False,
}

html_title = "Autonomous ETL Agent — Documentation"

# ── Source suffix ─────────────────────────────────────────────────────────────

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# ── Napoleon (Google-style docstrings) ───────────────────────────────────────

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True

# ── Autodoc ───────────────────────────────────────────────────────────────────

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_mock_imports = [
    "anthropic",
    "boto3",
    "botocore",
    "fastapi",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "alembic",
    "langgraph",
    "structlog",
    "tenacity",
    "pyspark",
    "httpx",
    "github",
    "redis",
]
