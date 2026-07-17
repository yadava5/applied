-- =============================================================================
-- JobTracker Database Schema
-- =============================================================================
-- This file is a reference for the database schema.
-- Tables are created by SQLModel, not this file.
--
-- Database: SQLite with WAL mode
-- Location: ~/Library/Application Support/JobTracker/jobtracker.db
-- =============================================================================

-- Enable Write-Ahead Logging for concurrent read/write access
-- (SwiftUI reads while Python writes)
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- =============================================================================
-- Applications Table
-- =============================================================================
-- Represents a job application to a company/position
-- Status tracks the application lifecycle

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    position TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied'
        CHECK(status IN (
            'applied', 'interviewing', 'offered',
            'rejected', 'accepted', 'withdrawn', 'ghosted'
        )),
    applied_date DATE,
    source TEXT,                            -- Where you found the job
    url TEXT,                               -- Job posting URL
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_company ON applications(company);

-- =============================================================================
-- Emails Table
-- =============================================================================
-- Synced emails from Gmail and iCloud with classification

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER REFERENCES applications(id) ON DELETE SET NULL,
    source_account TEXT NOT NULL            -- 'gmail' or 'icloud'
        CHECK(source_account IN ('gmail', 'icloud')),
    message_id TEXT UNIQUE NOT NULL,        -- Email Message-ID header (dedup key)
    thread_id TEXT,                         -- Gmail thread ID (null for iCloud)
    subject TEXT,
    sender_name TEXT,
    sender_email TEXT,
    received_at TIMESTAMP NOT NULL,
    body_text TEXT,
    body_html TEXT,                         -- Raw HTML body (rich rendering)
    body_snippet TEXT,                      -- First 500 chars for preview
    classified_as TEXT                      -- ML classification result
        CHECK(classified_as IN (
            'applied', 'pending_application', 'interview', 'rejection', 'offer',
            'assessment', 'follow_up', 'other'
        )),
    classification_confidence REAL,         -- 0.0 to 1.0
    classification_method TEXT              -- 'rules', 'similarity', 'setfit', 'user'
        CHECK(classification_method IN (
            'rules', 'similarity', 'setfit', 'user', 'fallback'
        )),
    user_corrected BOOLEAN DEFAULT 0,       -- Did user override classification?
    is_reviewed BOOLEAN DEFAULT 0,          -- Has user seen this email?
    raw_headers TEXT,                       -- JSON of email headers
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_emails_application ON emails(application_id);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_classified ON emails(classified_as);
CREATE INDEX IF NOT EXISTS idx_emails_source ON emails(source_account);
CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails(message_id);

-- =============================================================================
-- Full-Text Search (FTS5) Virtual Tables
-- =============================================================================
-- Enables fast search across:
-- - Application metadata: company, position, notes
-- - Email content: subject, sender, snippets/body

CREATE VIRTUAL TABLE IF NOT EXISTS applications_fts USING fts5(
    company,
    position,
    notes,
    content='applications',
    content_rowid='id',
    tokenize='porter'
);

CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    subject,
    sender_name,
    sender_email,
    body_text,
    body_snippet,
    content='emails',
    content_rowid='id',
    tokenize='porter'
);

-- =============================================================================
-- Contacts Table
-- =============================================================================
-- Recruiters and hiring managers associated with applications

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    name TEXT,
    email TEXT NOT NULL,
    role TEXT CHECK(role IN ('recruiter', 'hiring_manager', 'hr', 'other')),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contacts_application ON contacts(application_id);

-- =============================================================================
-- Interviews Table
-- =============================================================================
-- Scheduled interviews for applications

CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    type TEXT CHECK(type IN (
        'phone', 'video', 'onsite', 'technical', 'behavioral', 'panel'
    )),
    scheduled_at TIMESTAMP,
    duration_minutes INTEGER,
    location TEXT,                          -- Physical location or video link
    notes TEXT,
    status TEXT DEFAULT 'scheduled'
        CHECK(status IN ('scheduled', 'completed', 'cancelled', 'rescheduled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_interviews_application ON interviews(application_id);
CREATE INDEX IF NOT EXISTS idx_interviews_scheduled ON interviews(scheduled_at);

-- =============================================================================
-- Training Data Table
-- =============================================================================
-- User corrections for ML model improvement

CREATE TABLE IF NOT EXISTS training_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_text TEXT NOT NULL,
    label TEXT NOT NULL
        CHECK(label IN (
            'applied', 'pending_application', 'interview', 'rejection', 'offer',
            'assessment', 'follow_up', 'other'
        )),
    source TEXT DEFAULT 'user_correction',  -- 'user_correction' or 'manual_label'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_label ON training_data(label);

-- =============================================================================
-- Email Embeddings Table
-- =============================================================================
-- Stored embeddings for similarity-based classification (Layer 2)
-- Embeddings stored as BLOBs (384 floats = 1536 bytes)

CREATE TABLE IF NOT EXISTS email_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id INTEGER UNIQUE REFERENCES emails(id) ON DELETE CASCADE,
    label TEXT NOT NULL
        CHECK(label IN (
            'applied', 'pending_application', 'interview', 'rejection', 'offer',
            'assessment', 'follow_up', 'other'
        )),
    embedding BLOB NOT NULL,                -- numpy array serialized
    model_version TEXT DEFAULT 'e5-small-v2',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_embeddings_label ON email_embeddings(label);
CREATE INDEX IF NOT EXISTS idx_embeddings_email ON email_embeddings(email_id);

-- =============================================================================
-- Sync State Table
-- =============================================================================
-- Tracks last sync position for incremental email fetching

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_type TEXT NOT NULL              -- 'gmail' or 'icloud'
        CHECK(account_type IN ('gmail', 'icloud')),
    account_email TEXT NOT NULL UNIQUE,
    last_sync_at TIMESTAMP,
    gmail_history_id TEXT,                  -- For Gmail incremental sync
    imap_last_uid INTEGER,                  -- For IMAP incremental sync
    status TEXT DEFAULT 'idle'
        CHECK(status IN ('idle', 'syncing', 'error')),
    error_message TEXT
);

-- =============================================================================
-- Useful Queries (for reference)
-- =============================================================================

-- Count applications by status
-- SELECT status, COUNT(*) FROM applications GROUP BY status;

-- Count training data by label (for SetFit readiness check)
-- SELECT label, COUNT(*) FROM training_data GROUP BY label;

-- Get recent unclassified emails needing review
-- SELECT * FROM emails WHERE classification_confidence < 0.7 ORDER BY received_at DESC;

-- Get application pipeline stats
-- SELECT
--     COUNT(*) as total,
--     SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) as applied,
--     SUM(CASE WHEN status = 'interviewing' THEN 1 ELSE 0 END) as interviewing,
--     SUM(CASE WHEN status = 'offered' THEN 1 ELSE 0 END) as offered,
--     SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
-- FROM applications;
