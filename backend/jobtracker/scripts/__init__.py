"""
JobTracker Script Modules
=========================

Script entry points for data ingestion, ML evaluation, monitoring,
and weekly labeling workflows.

Scripts:
--------
- ingest_datasets.py: Parse raw dataset files → candidates.jsonl
- review_candidates.py: Terminal UI for manual label review
- import_to_db.py: Import verified candidates into training_data + embeddings
- weekly_labeling_workflow.py: Weekly privacy-safe real-signal labeling batch + KPI snapshot
- generate_ml_monitoring_report.py: Drift/confidence monitoring report + JSON artifacts
"""
