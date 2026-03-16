"""
Generate realistic Amazon Parquet fixture files for tests and demo.
Run: uv run python scripts/generate_fixtures.py
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path("tests/fixtures/data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
np.random.seed(SEED)

N_CUSTOMERS = 1_000
N_ORDERS = 10_000
N_CAMPAIGNS = 50
N_PRODUCTS = 20

REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America", "Middle East"]
COUNTRIES = {
    "North America": ["US", "CA", "MX"],
    "Europe": ["GB", "DE", "FR", "IT", "ES"],
    "Asia Pacific": ["JP", "IN", "AU", "SG", "KR"],
    "Latin America": ["BR", "AR", "CL"],
    "Middle East": ["AE", "SA", "IL"],
}
PRODUCT_CATEGORIES = ["iPhone 17", "MacBook Pro", "iPad Air", "AirPods Pro", "Apple Watch"]


def generate_customers() -> pd.DataFrame:
    """Generate amazon_customers.parquet"""
    region_list = np.random.choice(REGIONS, N_CUSTOMERS)
    country_list = [
        np.random.choice(COUNTRIES[r]) for r in region_list
    ]

    df = pd.DataFrame({
        "customer_id": [f"CUST-{i:06d}" for i in range(1, N_CUSTOMERS + 1)],
        "customer_name": [f"Customer {i}" for i in range(1, N_CUSTOMERS + 1)],
        "email": [f"customer{i}@example.com" for i in range(1, N_CUSTOMERS + 1)],
        "region": region_list,
        "country": country_list,
        "signup_date": pd.date_range("2020-01-01", periods=N_CUSTOMERS, freq="8h"),
        "customer_segment": np.random.choice(["Premium", "Standard", "Basic"], N_CUSTOMERS),
        "is_active": np.random.choice([True, False], N_CUSTOMERS, p=[0.85, 0.15]),
    })

    # Introduce 5% null values to test cleaning pipelines
    null_mask = np.random.choice([True, False], N_CUSTOMERS, p=[0.05, 0.95])
    df.loc[null_mask, "email"] = None

    out_path = OUTPUT_DIR / "amazon_customers.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    print(f"✅ {out_path} ({len(df):,} rows)")
    return df


def generate_orders(customers_df: pd.DataFrame) -> pd.DataFrame:
    """Generate amazon_orders.parquet"""
    base_date = datetime(2023, 1, 1)

    df = pd.DataFrame({
        "order_id": [f"ORD-{i:08d}" for i in range(1, N_ORDERS + 1)],
        "customer_id": np.random.choice(customers_df["customer_id"], N_ORDERS),
        "campaign_id": [f"CAMP-{np.random.randint(1, N_CAMPAIGNS + 1):04d}" for _ in range(N_ORDERS)],
        "product_category": np.random.choice(PRODUCT_CATEGORIES, N_ORDERS, p=[0.4, 0.25, 0.15, 0.1, 0.1]),
        "order_amount": np.round(np.random.exponential(scale=500, size=N_ORDERS), 2),
        "order_date": [base_date + timedelta(days=int(d)) for d in np.random.randint(0, 365, N_ORDERS)],
        "region": np.random.choice(REGIONS, N_ORDERS),
        "status": np.random.choice(["COMPLETED", "RETURNED", "PENDING"], N_ORDERS, p=[0.85, 0.10, 0.05]),
    })

    df["year"] = df["order_date"].dt.year
    df["month"] = df["order_date"].dt.month

    out_path = OUTPUT_DIR / "amazon_orders.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    print(f"✅ {out_path} ({len(df):,} rows)")
    return df


def generate_campaigns() -> pd.DataFrame:
    """Generate amazon_campaigns.parquet"""
    df = pd.DataFrame({
        "campaign_id": [f"CAMP-{i:04d}" for i in range(1, N_CAMPAIGNS + 1)],
        "campaign_name": [f"Campaign {i}" for i in range(1, N_CAMPAIGNS + 1)],
        "product_category": np.random.choice(PRODUCT_CATEGORIES, N_CAMPAIGNS, p=[0.4, 0.25, 0.15, 0.1, 0.1]),
        "impressions": np.random.randint(10_000, 1_000_000, N_CAMPAIGNS),
        "clicks": np.random.randint(1_000, 50_000, N_CAMPAIGNS),
        "campaign_cost": np.round(np.random.uniform(5_000, 100_000, N_CAMPAIGNS), 2),
        "start_date": pd.date_range("2023-01-01", periods=N_CAMPAIGNS, freq="7D"),
        "channel": np.random.choice(["Email", "Social", "Search", "Display"], N_CAMPAIGNS),
    })

    out_path = OUTPUT_DIR / "amazon_campaigns.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    print(f"✅ {out_path} ({len(df):,} rows)")
    return df


def generate_products() -> pd.DataFrame:
    """Generate amazon_products.parquet (focus: iPhone 17)"""
    products = [
        {"product_id": "PROD-001", "product_name": "iPhone 17", "category": "iPhone 17", "price": 999.99, "launch_date": "2024-09-15"},
        {"product_id": "PROD-002", "product_name": "iPhone 17 Plus", "category": "iPhone 17", "price": 1099.99, "launch_date": "2024-09-15"},
        {"product_id": "PROD-003", "product_name": "iPhone 17 Pro", "category": "iPhone 17", "price": 1199.99, "launch_date": "2024-09-15"},
        {"product_id": "PROD-004", "product_name": "iPhone 17 Pro Max", "category": "iPhone 17", "price": 1399.99, "launch_date": "2024-09-15"},
        {"product_id": "PROD-005", "product_name": "MacBook Pro 14", "category": "MacBook Pro", "price": 1999.99, "launch_date": "2024-01-01"},
        {"product_id": "PROD-006", "product_name": "MacBook Pro 16", "category": "MacBook Pro", "price": 2499.99, "launch_date": "2024-01-01"},
        {"product_id": "PROD-007", "product_name": "iPad Air 6", "category": "iPad Air", "price": 599.99, "launch_date": "2024-03-01"},
        {"product_id": "PROD-008", "product_name": "AirPods Pro 3", "category": "AirPods Pro", "price": 249.99, "launch_date": "2024-06-01"},
        {"product_id": "PROD-009", "product_name": "Apple Watch Series 10", "category": "Apple Watch", "price": 399.99, "launch_date": "2024-09-15"},
    ]

    df = pd.DataFrame(products)
    df["launch_date"] = pd.to_datetime(df["launch_date"])

    out_path = OUTPUT_DIR / "amazon_products.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    print(f"✅ {out_path} ({len(df):,} rows)")
    return df


if __name__ == "__main__":
    print("Generating Amazon Parquet fixtures...\n")
    customers = generate_customers()
    orders = generate_orders(customers)
    campaigns = generate_campaigns()
    products = generate_products()
    print(f"\n✅ All fixtures written to {OUTPUT_DIR}/")
