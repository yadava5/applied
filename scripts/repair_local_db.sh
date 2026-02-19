#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${1:-$HOME/Library/Application Support/JobTracker/jobtracker.db}"
BACKUP_DIR="${2:-$(dirname "$DB_PATH")/backups}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "Database not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

cp "$DB_PATH" "$BACKUP_DIR/jobtracker-$TIMESTAMP.db"
if [[ -f "$DB_PATH-wal" ]]; then
  cp "$DB_PATH-wal" "$BACKUP_DIR/jobtracker-$TIMESTAMP.db-wal"
fi
if [[ -f "$DB_PATH-shm" ]]; then
  cp "$DB_PATH-shm" "$BACKUP_DIR/jobtracker-$TIMESTAMP.db-shm"
fi

sqlite3 "$DB_PATH" <<'SQL'
PRAGMA wal_checkpoint(TRUNCATE);
REINDEX;
INSERT INTO applications_fts(applications_fts) VALUES('rebuild');
INSERT INTO emails_fts(emails_fts) VALUES('rebuild');
PRAGMA integrity_check;
SQL

echo "Repair steps complete."
echo "Backup saved under: $BACKUP_DIR"
