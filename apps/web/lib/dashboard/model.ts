/**
 * Single source of truth for the classifier's honest, code-verified numbers,
 * surfaced in the dashboard's "classifier context" tile. Every value here is
 * the same one the landing and System Card cite — kept in one place so the
 * dashboard can never drift from the model's real behaviour.
 *
 *   · AUTO_FILE_GATE — the 0.85 confidence gate (classifier/hybrid.py). Below
 *     it, nothing is auto-filed; the email waits for a human and the
 *     correction becomes new training data.
 *   · MACRO_F1       — 0.979 measured macro-F1 (baseline_hybrid_v3.json).
 *   · CI_FLOOR       — 0.95 CI gate; two GitHub Actions gates fail the build
 *     below it (backend-ci.yml).
 */
export const AUTO_FILE_GATE = 0.85;
export const MACRO_F1 = 0.979;
export const CI_FLOOR = 0.95;

/** Default auto-file gate a user starts from before they tune it in Settings. */
export const DEFAULT_GATE_PREFERENCE = AUTO_FILE_GATE;

/** Bounds the classification-preference slider can move the gate between. */
export const GATE_MIN = 0.5;
export const GATE_MAX = 0.99;
