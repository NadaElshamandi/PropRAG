-- ============================================================
--  Migration: Fix search_listings return type casts
--  Run this in: Supabase → SQL Editor → New Query
-- ============================================================

DROP FUNCTION IF EXISTS search_listings(vector(384), float, int, text, int, int, int);

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
        l.title::text,
        l.description,
        l.price_egp,
        l.area_sqm,
        l.bedrooms,
        l.bathrooms,
        loc.district::text,
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
