-- ════════════════════════════════════════════════════════════════
-- CS2 Instant Alert — PostgreSQL Initialization
-- Runs on first container start only
-- ════════════════════════════════════════════════════════════════

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Performance: enable pg_trgm for text search (future use)
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
