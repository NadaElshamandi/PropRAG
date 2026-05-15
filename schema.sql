-- ============================================================
--  Alexandria Real Estate Intelligence DB
--  Run this in: Supabase → SQL Editor → New Query
--  Order matters — run top to bottom
-- ============================================================


-- ── 0. Extensions ────────────────────────────────────────────
-- Enable the pgvector extension (vector similarity search)
CREATE EXTENSION IF NOT EXISTS vector;
-- uuid_generate_v4() for primary keys
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ── 1. sources ───────────────────────────────────────────────
-- Registry of every data source (OLX, Aqarmap, Facebook, etc.)
CREATE TABLE sources (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name             VARCHAR(100)  NOT NULL UNIQUE,   -- e.g. 'olx', 'aqarmap', 'facebook'
    base_url         VARCHAR(500),
    scraper_type     VARCHAR(50),                      -- 'playwright', 'requests', 'extension'
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE,
    last_scraped_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Seed the four sources right away
INSERT INTO sources (name, base_url, scraper_type) VALUES
    ('propertyfinder', 'https://www.propertyfinder.eg',       'playwright'),
    ('aqarmap',        'https://aqarmap.com.eg',              'playwright'),
    ('dubizzle',       'https://www.dubizzle.com.eg',       'playwright'),
    ('facebook',       'https://www.facebook.com/marketplace','extension');


-- ── 2. listings ──────────────────────────────────────────────
-- Core table — one row per unique apartment listing
CREATE TABLE listings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id       UUID          NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    external_id     VARCHAR(255),                      -- listing ID on the source platform
    listing_url     VARCHAR(1000),
    title           VARCHAR(500),
    description     TEXT,

    -- Pricing
    price_egp       INTEGER,                           -- price in Egyptian Pounds
    price_per_sqm   INTEGER GENERATED ALWAYS AS       -- auto-calculated
                    (CASE WHEN area_sqm > 0
                          THEN ROUND(price_egp / area_sqm)
                          ELSE NULL END) STORED,

    -- Physical specs
    area_sqm        FLOAT,
    bedrooms        INTEGER,
    bathrooms       INTEGER,
    floor           VARCHAR(50),                       -- '3', 'ground', 'roof'
    total_floors    INTEGER,
    finishing       VARCHAR(100),                      -- 'full finishing', 'semi', 'core & shell'
    has_elevator    BOOLEAN,
    has_parking     BOOLEAN,
    has_garden      BOOLEAN,
    has_pool        BOOLEAN,

    -- Lifecycle
    status          VARCHAR(50)   NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'sold', 'expired', 'flagged', 'duplicate')),
    first_seen_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    -- AI / vector search
    embedding       vector(1536),                     -- OpenAI text-embedding-3-small dimension

    -- Prevent exact duplicates from same source
    UNIQUE (source_id, external_id)
);

-- Indexes for common query patterns
CREATE INDEX idx_listings_source      ON listings(source_id);
CREATE INDEX idx_listings_status      ON listings(status);
CREATE INDEX idx_listings_price       ON listings(price_egp);
CREATE INDEX idx_listings_bedrooms    ON listings(bedrooms);
CREATE INDEX idx_listings_area        ON listings(area_sqm);
CREATE INDEX idx_listings_first_seen  ON listings(first_seen_at DESC);

-- IVFFlat index for vector similarity search (cosine distance)
-- Run AFTER inserting at least a few hundred rows for best performance
CREATE INDEX idx_listings_embedding
    ON listings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Auto-update updated_at on any change
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_listings_updated_at
    BEFORE UPDATE ON listings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- ── 3. locations ─────────────────────────────────────────────
-- Geographic info for each listing (1-to-1 with listings)
CREATE TABLE locations (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    listing_id     UUID          NOT NULL UNIQUE REFERENCES listings(id) ON DELETE CASCADE,
    district       VARCHAR(150),                      -- e.g. 'Smouha', 'Sidi Gaber', 'Miami'
    neighborhood   VARCHAR(150),
    street         VARCHAR(300),
    latitude       FLOAT,
    longitude      FLOAT,
    raw_address    TEXT                               -- original address string from source
);

CREATE INDEX idx_locations_listing    ON locations(listing_id);
CREATE INDEX idx_locations_district   ON locations(district);
-- Geospatial index (useful if you add PostGIS later)
CREATE INDEX idx_locations_coords     ON locations(latitude, longitude);


-- ── 4. contacts ──────────────────────────────────────────────
-- Seller or agent contact details per listing
CREATE TABLE contacts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    listing_id  UUID          NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    name        VARCHAR(255),
    phone       VARCHAR(50),
    whatsapp    VARCHAR(50),
    type        VARCHAR(50)   DEFAULT 'unknown'
                CHECK (type IN ('owner', 'agent', 'developer', 'unknown')),
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_contacts_listing  ON contacts(listing_id);
CREATE INDEX idx_contacts_phone    ON contacts(phone);     -- detect same agent across platforms


-- ── 5. media ─────────────────────────────────────────────────
-- Photos and videos for each listing
CREATE TABLE media (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    listing_id  UUID          NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    url         VARCHAR(1000) NOT NULL,
    media_type  VARCHAR(20)   DEFAULT 'image'
                CHECK (media_type IN ('image', 'video', 'floor_plan')),
    sort_order  INTEGER       DEFAULT 0,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_media_listing ON media(listing_id);


-- ── 6. scrape_logs ───────────────────────────────────────────
-- Audit trail: every scraper run is recorded here
CREATE TABLE scrape_logs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id           UUID          NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    listings_found      INTEGER       DEFAULT 0,
    new_listings        INTEGER       DEFAULT 0,
    duplicates_skipped  INTEGER       DEFAULT 0,
    status              VARCHAR(50)   DEFAULT 'success'
                        CHECK (status IN ('success', 'partial', 'failed')),
    error_message       TEXT,
    duration_seconds    FLOAT,
    ran_at              TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scrape_logs_source  ON scrape_logs(source_id);
CREATE INDEX idx_scrape_logs_ran_at  ON scrape_logs(ran_at DESC);


-- ── 7. user_notes ────────────────────────────────────────────
-- Your personal annotations on top of scraped data
CREATE TABLE user_notes (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    listing_id  UUID          NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    note        TEXT,
    tag         VARCHAR(100),                         -- 'shortlist', 'overpriced', 'visited', etc.
    is_favorite BOOLEAN       DEFAULT FALSE,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_notes_listing    ON user_notes(listing_id);
CREATE INDEX idx_user_notes_favorite   ON user_notes(is_favorite);
CREATE INDEX idx_user_notes_tag        ON user_notes(tag);

CREATE TRIGGER trg_user_notes_updated_at
    BEFORE UPDATE ON user_notes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- ── 8. Useful views ──────────────────────────────────────────

-- Full listing view (joins all tables for easy querying)
CREATE OR REPLACE VIEW v_listings_full AS
SELECT
    l.id,
    l.title,
    l.price_egp,
    l.price_per_sqm,
    l.area_sqm,
    l.bedrooms,
    l.bathrooms,
    l.floor,
    l.finishing,
    l.has_elevator,
    l.has_parking,
    l.status,
    l.listing_url,
    l.first_seen_at,
    s.name          AS source,
    loc.district,
    loc.neighborhood,
    loc.street,
    loc.latitude,
    loc.longitude,
    un.is_favorite,
    un.tag,
    un.note
FROM listings l
JOIN sources  s   ON s.id  = l.source_id
LEFT JOIN locations  loc ON loc.listing_id = l.id
LEFT JOIN user_notes un  ON un.listing_id  = l.id
WHERE l.status != 'duplicate';

-- Scraper health dashboard view
CREATE OR REPLACE VIEW v_scraper_health AS
SELECT
    s.name,
    s.is_active,
    s.last_scraped_at,
    COUNT(sl.id)                                          AS total_runs,
    SUM(sl.new_listings)                                  AS total_listings_collected,
    ROUND(AVG(sl.duration_seconds)::numeric, 1)           AS avg_duration_sec,
    MAX(sl.ran_at)                                        AS last_run,
    SUM(CASE WHEN sl.status = 'failed' THEN 1 ELSE 0 END) AS failed_runs
FROM sources s
LEFT JOIN scrape_logs sl ON sl.source_id = s.id
GROUP BY s.id, s.name, s.is_active, s.last_scraped_at;

-- Duplicate detection view (same phone number on multiple listings)
CREATE OR REPLACE VIEW v_potential_duplicates AS
SELECT
    c.phone,
    COUNT(DISTINCT l.id)   AS listing_count,
    ARRAY_AGG(DISTINCT s.name) AS sources,
    ARRAY_AGG(l.listing_url)   AS urls
FROM contacts c
JOIN listings l ON l.id = c.listing_id
JOIN sources  s ON s.id = l.source_id
WHERE c.phone IS NOT NULL
GROUP BY c.phone
HAVING COUNT(DISTINCT l.id) > 1;


-- ── 9. Row Level Security (RLS) ──────────────────────────────
-- Enable RLS so only your authenticated Supabase user can read/write
ALTER TABLE listings    ENABLE ROW LEVEL SECURITY;
ALTER TABLE locations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts    ENABLE ROW LEVEL SECURITY;
ALTER TABLE media       ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources     ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_notes  ENABLE ROW LEVEL SECURITY;

-- Policy: only the service role (your Python scrapers) and authenticated users can access
CREATE POLICY "service role full access" ON listings    FOR ALL USING (TRUE);
CREATE POLICY "service role full access" ON locations   FOR ALL USING (TRUE);
CREATE POLICY "service role full access" ON contacts    FOR ALL USING (TRUE);
CREATE POLICY "service role full access" ON media       FOR ALL USING (TRUE);
CREATE POLICY "service role full access" ON sources     FOR ALL USING (TRUE);
CREATE POLICY "service role full access" ON scrape_logs FOR ALL USING (TRUE);
CREATE POLICY "service role full access" ON user_notes  FOR ALL USING (TRUE);


-- ── Done ─────────────────────────────────────────────────────
-- Verify everything was created:
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
