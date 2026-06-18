-- Migration: Add Bayut source
-- Run this in Supabase SQL Editor if you haven't re-run schema.sql

INSERT INTO sources (name, base_url, scraper_type)
VALUES ('bayut', 'https://www.bayut.eg', 'api')
ON CONFLICT (name) DO NOTHING;
