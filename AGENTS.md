# 🤖 AGENTS.md: PropRAG Autonomous Operations

## 🏠 Project Overview: PropRAG
PropRAG is a RAG-enabled Property Management System. It doesn't just store data; it utilizes an autonomous agentic loop to curate, validate, and serve the Alexandria real estate market.

**Objective:** Maintain a real-time, semantically searchable twin of Alexandria's property market.

**Core Loop:** Perceive (Scrape) → Reason (Filter/Normalize) → Act (Upsert/Embed) → Observe (Validate).

## 🛠 Tech Stack & Agentic Framework

- **Orchestration:** ohmyopenagent (Sisyphus for persistence, Hephaestus for extraction).
- **Intelligence:** OpenCode Go (Kimi K2.6 / GLM-5.1) for high-reasoning tasks.
- **Standardization:** Model Context Protocol (MCP) for database and scraper tool-calling.
- **Memory:**
  - *Short-term:* Redis/Local cache for session-based deduplication.
  - *Long-term:* Supabase (PostgreSQL + pgvector) for historical trend analysis.

## 🔄 The Agentic Workflow (ReAct Pattern)

### 1. Data Perception (The Scrapers)
Agents must treat scrapers as tools, not just scripts.

- **Autonomous Navigation:** If Playwright encounters a modal or layout shift, the agent must use the LLM to analyze the DOM and propose a new selector path.
- **Bilingual Normalization:** Automatically map "Glym" / "جليم" and "Sidi Gaber" / "سيدي جابر" to the canonical IDs in districts.json.

### 2. Reasoning & Validation
Before any data reaches the database, a Reflection Agent must:

- **Outlier Detection:** Is a property in "Agami" priced like a villa in "Kafr Abdou"? Flag for human review or re-scrape.
- **Geographic Verification:** Ensure the listing is actually within Alexandria boundaries and not "North Coast" (Sahel).

### 3. Action (Upsert & Embed)

- **Smart Embedding:** Only trigger OpenAI/Kimi embedding calls if the description or price hash has changed.
- **Hybrid Search:** Combine metadata filters (price, rooms) with vector similarity to ensure "San Stefano" results prioritize beachfront proximity.

## 🎨 Agentic Code Style & Guidelines

- **Simplicity & Types:** Use Pydantic models for all agent "Thought" and "Action" schemas.
- **MCP Integration:** All database interactions should eventually move to an MCP server to allow cross-agent tool usage.
- **Async Everywhere:** Use asyncio to manage concurrent agent "thinking" time and scraper I/O.

## 🔒 Security & Resilience (The "Safety" Loop)

- **Defensive Scraping:** If an agent detects a 403 (Forbidden), it must trigger an Exponential Backoff and switch to a new proxy/User-Agent.
- **Secret Management:** Agents are strictly prohibited from logging or printing .env variables (Supabase keys, API tokens).

## 📂 Data Management & Deduplication

- **Identity:** The source_url is the primary key.
- **Context Injection:** When a user queries the system, the agent should inject the current Alexandria market trends (average price/sqm in that district) into the prompt context to provide "Consultant-style" answers.

## 🚢 Deployment & CI/CD

- **Evaluation (LLM-as-a-Judge):** Use GitHub Actions to run OpenCode Go against new scraper logic. The "Judge" agent must verify that the parser still correctly extracts prices from the Dubizzle "Price" div.
- **Architecture:** Containerized worker agents (Docker) targeting ARM64/AMD64.

## ✍️ Specific Agent Instructions

- **Commit Messages:** Follow Conventional Commits.
- **Self-Correction:** If a pgvector query returns zero results, the agent should automatically broaden the search to neighboring districts (e.g., if "Loran" is empty, check "Saray" and "Glym").
- **Efficiency:** Use Sisyphus for long-running monitoring and Hephaestus for heavy data transformation.
