/**
 * Single source of truth for the classifier's honest, code-verified numbers,
 * surfaced in the dashboard's "classifier context" tile. Every value here is
 * the same one the landing and System Card cite — kept in one place so the
 * dashboard can never drift from the model's real behaviour.
 *
 *   · AUTO_FILE_GATE — the confidence gate. Below it, nothing is auto-filed;
 *     the email waits for a human and the correction becomes new training
 *     data. This is the ONE web definition of that number (#229 collapsed a
 *     second copy in components/viz/GateMeter.tsx into it), and it is held in
 *     lock-step with the backend's `CONFIDENCE_AUTO`
 *     (backend/jobtracker/classifier/hybrid.py) by an invariant in
 *     `scripts/readme_facts.py`, which reads both languages and fails when
 *     either side moves alone. The value is deliberately not restated in this
 *     comment: a number written twice in one file is a number that gets
 *     corrected once.
 *   · MACRO_F1       — 0.979 measured macro-F1 (baseline_hybrid_v3.json).
 *   · CI_FLOOR       — 0.95 CI gate; two GitHub Actions gates fail the build
 *     below it (backend-ci.yml).
 */
export const AUTO_FILE_GATE = 0.85;
export const MACRO_F1 = 0.979;
export const CI_FLOOR = 0.95;

// `DEFAULT_GATE_PREFERENCE`, `GATE_MIN` and `GATE_MAX` used to live here, to
// bound a Settings slider. The slider wrote a per-user threshold into Supabase
// user metadata and no backend ever read it (#208), and the gate is ONE number for
// every account — so a "default a user starts from before they tune it" and a
// range to tune it across were both describing a product that does not exist.
// `AUTO_FILE_GATE` above is the whole story; the per-message override is the
// review queue.
