"""
db.py
-----
Centralized database client for PropRAG.
Handles Supabase connection, listing upserts, embedding generation,
and hybrid vector + metadata search.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client, Client

from scrapers.neighborhoods import normalize_district

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("DBClient")


class DBClient:
    """
    Thin wrapper around Supabase + OpenAI for PropRAG operations.

    Responsibilities:
        - source ↔ UUID resolution
        - listing upsert with deduplication
        - embedding generation (lazy: only for new listings)
        - hybrid vector + metadata search via pgvector RPC
    """

    def __init__(self):
        self.supabase: Client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
        openai_key = os.environ.get("OPENAI_API_KEY")
        self.openai = OpenAI(api_key=openai_key) if openai_key else None

    # ── Source helpers ───────────────────────────────────────────────────────

    def get_source_id(self, source_name: str) -> str:
        """Fetch a source UUID by its human-readable name."""
        res = (
            self.supabase.table("sources")
            .select("id")
            .eq("name", source_name)
            .single()
            .execute()
        )
        return res.data["id"]

    # ── Embedding ────────────────────────────────────────────────────────────

    def generate_embedding(self, text: str) -> list[float]:
        """Generate a 1536-dim OpenAI text-embedding-3-small vector."""
        if not self.openai:
            logger.warning("OPENAI_API_KEY not set; skipping embedding generation")
            return []
        if not text or not text.strip():
            return []
        try:
            response = self.openai.embeddings.create(
                model="text-embedding-3-small",
                input=text.strip()[:8000],  # token limit safety
            )
            return response.data[0].embedding
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return []

    # ── Upsert ───────────────────────────────────────────────────────────────

    def upsert_listing(self, source_id: str, data: dict) -> tuple[Optional[str], bool]:
        """
        Insert a new listing or touch last_seen_at if it already exists.
        Generates an embedding ONLY for brand-new listings.
        Normalizes district names before writing to locations.

        Returns (listing_uuid, is_new).
        is_new=True  → fresh insert with embedding
        is_new=False → duplicate touched (last_seen_at updated)
        """
        external_id = data.get("external_id")
        if not external_id:
            logger.warning("upsert_listing called without external_id")
            return None, False

        # ── Deduplication ──────────────────────────────────────────────────
        existing = (
            self.supabase.table("listings")
            .select("id")
            .eq("source_id", source_id)
            .eq("external_id", external_id)
            .execute()
        )

        if existing.data:
            listing_id = existing.data[0]["id"]
            self.supabase.table("listings").update(
                {"last_seen_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", listing_id).execute()
            logger.debug(f"Updated last_seen_at for existing listing {external_id}")
            return listing_id, False

        # ── Prepare payload ────────────────────────────────────────────────
        listing_payload = {
            k: v for k, v in data.items()
            if k not in ("location", "contacts", "media")
        }
        listing_payload["source_id"] = source_id
        listing_payload["status"] = data.get("status", "active")
        now = datetime.now(timezone.utc).isoformat()
        listing_payload["first_seen_at"] = now
        listing_payload["last_seen_at"] = now

        # Generate embedding for new listings
        desc = listing_payload.get("description", "")
        if desc:
            embedding = self.generate_embedding(desc)
            if embedding:
                listing_payload["embedding"] = embedding

        # ── Insert listing ─────────────────────────────────────────────────
        res = self.supabase.table("listings").insert(listing_payload).execute()
        listing_id = res.data[0]["id"]
        logger.info(f"  ✓ Saved new listing: {data.get('title', '')[:60]}")

        # ── Insert related rows ──────────────────────────────────────────
        location = data.get("location", {})
        if location:
            raw_district = location.get("district")
            if raw_district:
                location["district"] = normalize_district(raw_district) or raw_district

            self.supabase.table("locations").insert(
                {"listing_id": listing_id, **location}
            ).execute()

        for contact in data.get("contacts", []):
            self.supabase.table("contacts").insert(
                {"listing_id": listing_id, **contact}
            ).execute()

        for i, url in enumerate(data.get("media", [])):
            self.supabase.table("media").insert(
                {"listing_id": listing_id, "url": url, "sort_order": i}
            ).execute()

        return listing_id, True

    # ── Search ─────────────────────────────────────────────────────────────────

    def search_listings(
        self,
        query: str,
        *,
        district: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        bedrooms: Optional[int] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Hybrid RAG search:
            1. Embed the user query
            2. Call the pgvector `search_listings` RPC with metadata filters
        """
        embedding = self.generate_embedding(query)
        if not embedding:
            logger.warning("Empty embedding for query; falling back to metadata-only search")
            return self._metadata_only_search(
                district=district,
                min_price=min_price,
                max_price=max_price,
                bedrooms=bedrooms,
                limit=limit,
            )

        params = {
            "query_embedding": embedding,
            "match_threshold": 0.7,
            "match_count": limit,
            "filter_district": normalize_district(district) if district else None,
            "min_price": min_price,
            "max_price": max_price,
            "min_bedrooms": bedrooms,
        }

        res = self.supabase.rpc("search_listings", params).execute()
        return res.data or []

    def _metadata_only_search(
        self,
        *,
        district: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        bedrooms: Optional[int] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Fallback when embedding is unavailable."""
        q = (
            self.supabase.table("listings")
            .select("*, locations(district)")
            .eq("status", "active")
            .limit(limit)
        )
        if district:
            # We can't filter on joined columns easily via REST,
            # so we fetch and filter in Python for the fallback.
            pass
        if min_price is not None:
            q = q.gte("price_egp", min_price)
        if max_price is not None:
            q = q.lte("price_egp", max_price)
        if bedrooms is not None:
            q = q.gte("bedrooms", bedrooms)

        res = q.execute()
        rows = res.data or []

        if district:
            norm = normalize_district(district)
            rows = [
                r for r in rows
                if r.get("locations", {}).get("district") == norm
            ]
        return rows
