Olist Dataset
=============

What is Olist?
--------------

Olist is a Brazilian e-commerce marketplace connector that links small businesses to large
retail channels. The `Brazilian E-Commerce Public Dataset by Olist
<https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce>`_ is a publicly available
dataset on Kaggle containing anonymised order, customer, seller, product, and review
data from 2016 to 2018.

This dataset is used as the source data for all pipeline runs in this project. It provides
a realistic, multi-table relational dataset that exercises JOINs, aggregations, null
handling, date parsing, and other common ETL operations.

Dataset Tables
--------------

The dataset consists of 9 CSV files, each uploaded to a dedicated S3 prefix under
``s3://etl-agent-raw-prod/olist/`` and registered as a separate table in the AWS Glue
Data Catalog.

orders
~~~~~~

The central fact table. One row per order.

.. list-table::
   :header-rows: 1
   :widths: 35 12 53

   * - Column
     - Type
     - Description
   * - order_id
     - string
     - Unique order identifier (primary key)
   * - customer_id
     - string
     - Foreign key → customers
   * - order_status
     - string
     - ``created``, ``approved``, ``shipped``, ``delivered``, ``canceled``, ``unavailable``, ``invoiced``, ``processing``
   * - order_purchase_timestamp
     - string
     - Timestamp when customer placed the order
   * - order_approved_at
     - string
     - Timestamp of payment approval
   * - order_delivered_carrier_date
     - string
     - Timestamp when order was handed to carrier
   * - order_delivered_customer_date
     - string
     - Actual delivery timestamp
   * - order_estimated_delivery_date
     - string
     - Estimated delivery timestamp shown to customer

order_items
~~~~~~~~~~~

One row per item within an order. An order can have multiple items from different sellers.

======================== ======= =====================================================
Column                   Type    Description
======================== ======= =====================================================
order_id                 string  Foreign key → orders
order_item_id            int     Sequential item number within the order (1, 2, 3 …)
product_id               string  Foreign key → products
seller_id                string  Foreign key → sellers
shipping_limit_date      string  Deadline for the seller to ship
price                    double  Item price in BRL
freight_value            double  Freight cost charged for this item
======================== ======= =====================================================

order_payments
~~~~~~~~~~~~~~

One row per payment instalment. An order can be paid in multiple instalments or with
multiple payment methods.

===================== ======= =====================================================
Column                Type    Description
===================== ======= =====================================================
order_id              string  Foreign key → orders
payment_sequential    int     Payment sequence number (1 = first payment)
payment_type          string  ``credit_card``, ``boleto``, ``voucher``, ``debit_card``
payment_installments  int     Number of instalments chosen
payment_value         double  Transaction value in BRL
===================== ======= =====================================================

order_reviews
~~~~~~~~~~~~~

Customer satisfaction review submitted after delivery.

======================== ======= =====================================================
Column                   Type    Description
======================== ======= =====================================================
review_id                string  Unique review identifier
order_id                 string  Foreign key → orders
review_score             int     1–5 star rating
review_comment_title     string  Optional short title (Portuguese)
review_comment_message   string  Optional long message (Portuguese)
review_creation_date     string  Timestamp when review was created
review_answer_timestamp  string  Timestamp when seller responded
======================== ======= =====================================================

customers
~~~~~~~~~

One row per customer. Note that the same physical customer may appear multiple times
with different ``customer_id`` values if they placed orders under different accounts.

========================= ======= =====================================================
Column                    Type    Description
========================= ======= =====================================================
customer_id               string  Primary key (unique per order, not per person)
customer_unique_id        string  Persistent ID that links multiple orders by the
                                  same person
customer_zip_code_prefix  string  5-digit postal code prefix
customer_city             string  City name (Portuguese)
customer_state            string  2-letter Brazilian state abbreviation
========================= ======= =====================================================

sellers
~~~~~~~

Seller (merchant) dimension table.

========================= ======= =====================================================
Column                    Type    Description
========================= ======= =====================================================
seller_id                 string  Unique seller identifier (primary key)
seller_zip_code_prefix    string  5-digit postal code prefix
seller_city               string  City name
seller_state              string  2-letter Brazilian state abbreviation
========================= ======= =====================================================

products
~~~~~~~~

Product catalogue. Product names and descriptions are in Portuguese.

=========================== ======= =====================================================
Column                      Type    Description
=========================== ======= =====================================================
product_id                  string  Unique product identifier (primary key)
product_category_name       string  Portuguese category name
product_name_lenght         int     Number of characters in product name
product_description_lenght  int     Number of characters in description
product_photos_qty          int     Number of product photos
product_weight_g            double  Weight in grams
product_length_cm           double  Length in centimetres
product_height_cm           double  Height in centimetres
product_width_cm            double  Width in centimetres
=========================== ======= =====================================================

geolocation
~~~~~~~~~~~

Maps Brazilian ZIP code prefixes to geographic coordinates. Contains multiple rows
per ZIP prefix (different lat/lon measurements). ~1 million rows — the largest table.

.. list-table::
   :header-rows: 1
   :widths: 35 12 53

   * - Column
     - Type
     - Description
   * - geolocation_zip_code_prefix
     - string
     - 5-digit postal code prefix
   * - geolocation_lat
     - double
     - Latitude
   * - geolocation_lng
     - double
     - Longitude
   * - geolocation_city
     - string
     - City name
   * - geolocation_state
     - string
     - 2-letter state abbreviation

product_category_translation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maps Portuguese product category names to English equivalents.

============================== ======= =====================================================
Column                         Type    Description
============================== ======= =====================================================
product_category_name          string  Portuguese category name (foreign key → products)
product_category_name_english  string  English translation
============================== ======= =====================================================

Entity Relationship
-------------------

.. mermaid::

   %%{init: {'theme': 'default', 'themeVariables': {'background': '#ffffff', 'lineColor': '#333333', 'primaryColor': '#B3D4FF', 'primaryTextColor': '#000000', 'primaryBorderColor': '#1A56BB', 'attributeBackgroundColorEven': '#f0f4ff', 'attributeBackgroundColorOdd': '#ffffff'}}}%%
   erDiagram
       customers {
           string customer_id PK
           string customer_unique_id
           string customer_zip_code_prefix FK
           string customer_city
           string customer_state
       }
       orders {
           string order_id PK
           string customer_id FK
           string order_status
           string order_purchase_timestamp
           string order_delivered_customer_date
           string order_estimated_delivery_date
       }
       order_items {
           string order_id FK
           int    order_item_id
           string product_id FK
           string seller_id FK
           double price
           double freight_value
       }
       order_payments {
           string order_id FK
           int    payment_sequential
           string payment_type
           int    payment_installments
           double payment_value
       }
       order_reviews {
           string review_id PK
           string order_id FK
           int    review_score
           string review_creation_date
       }
       products {
           string product_id PK
           string product_category_name FK
           double product_weight_g
           double product_length_cm
       }
       sellers {
           string seller_id PK
           string seller_zip_code_prefix FK
           string seller_city
           string seller_state
       }
       geolocation {
           string geolocation_zip_code_prefix PK
           double geolocation_lat
           double geolocation_lng
           string geolocation_city
           string geolocation_state
       }
       product_category_translation {
           string product_category_name PK
           string product_category_name_english
       }

       customers ||--o{ orders : "places"
       orders ||--o{ order_items : "contains"
       orders ||--o{ order_payments : "paid via"
       orders ||--o{ order_reviews : "reviewed in"
       order_items }o--|| products : "references"
       order_items }o--|| sellers : "fulfilled by"
       customers }o--|| geolocation : "located in"
       sellers }o--|| geolocation : "located in"
       products }o--o| product_category_translation : "translated by"

Uploading the Data to S3
------------------------

Download the dataset from Kaggle and upload each CSV to its corresponding S3 prefix:

.. code-block:: bash

    # Download from Kaggle (requires kaggle CLI: pip install kaggle)
    kaggle datasets download olistbr/brazilian-ecommerce
    unzip brazilian-ecommerce.zip -d olist/

    # Upload to S3 (replace bucket name as needed)
    BUCKET=etl-agent-raw-prod

    aws s3 cp olist/olist_orders_dataset.csv              s3://$BUCKET/olist/orders/
    aws s3 cp olist/olist_order_items_dataset.csv         s3://$BUCKET/olist/order_items/
    aws s3 cp olist/olist_order_payments_dataset.csv      s3://$BUCKET/olist/order_payments/
    aws s3 cp olist/olist_order_reviews_dataset.csv       s3://$BUCKET/olist/order_reviews/
    aws s3 cp olist/olist_customers_dataset.csv           s3://$BUCKET/olist/customers/
    aws s3 cp olist/olist_sellers_dataset.csv             s3://$BUCKET/olist/sellers/
    aws s3 cp olist/olist_products_dataset.csv            s3://$BUCKET/olist/products/
    aws s3 cp olist/olist_geolocation_dataset.csv         s3://$BUCKET/olist/geolocation/
    aws s3 cp olist/product_category_name_translation.csv s3://$BUCKET/olist/product_category_translation/

After uploading, run the Glue Crawler to register the schemas:

.. code-block:: bash

    aws glue start-crawler --name etl-agent-olist-crawler

    # Wait for completion (takes 1–3 minutes)
    aws glue get-crawler --name etl-agent-olist-crawler \
        --query 'Crawler.State' --output text

Once the crawler state returns ``READY``, all 9 tables are registered in the
``etl_agent_catalog`` database and the agent can use them.

Sample Pipeline Stories
-----------------------

The following user stories are good starting points for testing the agent with this dataset:

**Filter delivered orders**

    Title: ``Filter Active Olist Orders``

    Description: As a data analyst, I want to filter the Olist orders dataset to include only
    delivered orders, so that downstream revenue reports reflect completed transactions only.

    Acceptance Criteria:
    - Output contains only orders where order_status = 'delivered'
    - Row count is greater than 0
    - No null values in order_id column

**Revenue by seller**

    Title: ``Calculate Revenue by Seller``

    Description: Join order_items with orders to calculate total revenue per seller for
    delivered orders, excluding cancelled or unavailable orders.

    Acceptance Criteria:
    - Output has one row per seller_id
    - revenue column is the sum of price + freight_value
    - Only delivered orders are included
    - Output sorted by revenue descending

**Customer RFM segmentation**

    Title: ``Customer RFM Segmentation``

    Description: Compute Recency, Frequency, and Monetary scores for each unique customer
    using the customer_unique_id from the customers table joined to orders and order_payments.

    Acceptance Criteria:
    - One row per customer_unique_id
    - recency_days = days since last order_purchase_timestamp
    - frequency = total number of distinct orders
    - monetary = total payment_value
