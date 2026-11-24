CREATE TABLE IF NOT EXISTS categories (
    category_id BIGSERIAL PRIMARY KEY,
    category_name VARCHAR(120) NOT NULL,
    category_path VARCHAR(500) NOT NULL UNIQUE,
    parent_category_id BIGINT REFERENCES categories(category_id),
    CONSTRAINT categories_not_own_parent CHECK (parent_category_id IS NULL OR parent_category_id <> category_id)
);

CREATE TABLE IF NOT EXISTS products (
    product_id BIGSERIAL PRIMARY KEY,
    product_sku VARCHAR(50) NOT NULL UNIQUE,
    product_name VARCHAR(255) NOT NULL,
    category_id BIGINT REFERENCES categories(category_id),
    list_unit_price NUMERIC(12, 2) CHECK (list_unit_price IS NULL OR list_unit_price >= 0)
);

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id BIGSERIAL PRIMARY KEY,
    platform VARCHAR(30) NOT NULL,
    campaign_name VARCHAR(200) NOT NULL,
    CONSTRAINT campaigns_platform_name_unique UNIQUE (platform, campaign_name)
);

CREATE TABLE IF NOT EXISTS daily_ad_spend (
    spend_id BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL REFERENCES campaigns(campaign_id),
    spend_date DATE NOT NULL,
    ad_spend NUMERIC(14, 2) NOT NULL CHECK (ad_spend >= 0),
    impressions BIGINT NOT NULL DEFAULT 0 CHECK (impressions >= 0),
    clicks BIGINT NOT NULL DEFAULT 0 CHECK (clicks >= 0),
    CONSTRAINT daily_ad_spend_campaign_date_unique UNIQUE (campaign_id, spend_date)
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id BIGSERIAL PRIMARY KEY,
    customer_key VARCHAR(260) NOT NULL UNIQUE,
    phone_normalized VARCHAR(16) UNIQUE,
    email_normalized VARCHAR(200),
    customer_state VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS leads (
    lead_pk BIGSERIAL PRIMARY KEY,
    lead_id VARCHAR(50) NOT NULL UNIQUE,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    campaign_id BIGINT REFERENCES campaigns(campaign_id),
    lead_created_at TIMESTAMPTZ NOT NULL,
    lead_name VARCHAR(200),
    CONSTRAINT leads_created_at_not_future CHECK (lead_created_at < TIMESTAMPTZ '2100-01-01 00:00:00+00')
);

CREATE TABLE IF NOT EXISTS orders (
    order_pk BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL UNIQUE,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    order_date TIMESTAMPTZ NOT NULL,
    order_status VARCHAR(30) NOT NULL,
    order_total NUMERIC(14, 2) NOT NULL CHECK (order_total >= 0),
    payment_mode VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id BIGSERIAL PRIMARY KEY,
    order_pk BIGINT NOT NULL REFERENCES orders(order_pk) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    gst_percent NUMERIC(5, 2) NOT NULL CHECK (gst_percent >= 0 AND gst_percent <= 100),
    CONSTRAINT order_items_order_product_unique UNIQUE (order_pk, product_id)
);

CREATE TABLE IF NOT EXISTS migration_rejects (
    reject_id BIGSERIAL PRIMARY KEY,
    legacy_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    source_row JSONB NOT NULL,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
