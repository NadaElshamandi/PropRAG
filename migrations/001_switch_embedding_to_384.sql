-- ============================================================
--  Migration: Switch embedding from vector(1536) → vector(384)
--  Run this in: Supabase → SQL Editor → New Query
-- ============================================================

-- 1. Drop the old vector index
DROP INDEX IF EXISTS idx_listings_embedding;

-- 2. Drop the old search function (depends on vector(1536))
DROP FUNCTION IF EXISTS search_listings(
    vector(1536), float, int, text, int, int, int
);

-- 3. Drop the old embedding column
ALTER TABLE listings DROP COLUMN IF EXISTS embedding;

-- 4. Add the new embedding column (384-dim for all-MiniLM-L6-v2)
ALTER TABLE listings ADD COLUMN embedding vector(384);

-- 5. Recreate the vector index
CREATE INDEX idx_listings_embedding
    ON listings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- 6. Recreate the search function with vector(384)
CREATE OR REPLACE FUNCTION search_listings(
    query_embedding vector(384),
    match_threshold float,
    match_count int,
    filter_district text DEFAULT NULL,
    min_price int DEFAULT NULL,
    max_price int DEFAULT NULL,
    min_bedrooms int DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    title text,
    description text,
    price_egp int,
    area_sqm float,
    bedrooms int,
    bathrooms int,
    district text,
    similarity float
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        l.id,
        l.title,
        l.description,
        l.price_egp,
        l.area_sqm,
        l.bedrooms,
        l.bathrooms,
        loc.district,
        1 - (l.embedding <=> query_embedding) AS similarity
    FROM listings l
    LEFT JOIN locations loc ON loc.listing_id = l.id
    WHERE l.status = 'active'
      AND l.embedding IS NOT NULL
      AND (1 - (l.embedding <=> query_embedding)) > match_threshold
      AND (filter_district IS NULL OR loc.district = filter_district)
      AND (min_price IS NULL OR l.price_egp >= min_price)
      AND (max_price IS NULL OR l.price_egp <= max_price)
      AND (min_bedrooms IS NULL OR l.bedrooms >= min_bedrooms)
    ORDER BY l.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- 7. Verify
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'listings' AND column_name = 'embedding';
