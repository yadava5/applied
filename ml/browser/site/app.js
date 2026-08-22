/* JobTracker classifier, in-browser.
 *
 * Faithful port of the 3-layer hybrid (backend/jobtracker/classifier):
 *   1. rules       — same 221 regexes, same scoring (strong +3 ×2-subject,
 *                    weak +1, negative −5, veto caps the category at 0),
 *                    same margin→confidence tiers, same ATS-domain boost.
 *                    Accept ≥0.9.
 *   2. embeddings  — cosine vs a synthetic example bank embedded with the
 *                    fine-tuned body ("query: " prefix). Accept ≥0.85.
 *   3. setfit      — LogisticRegression head over the same embedding
 *                    (no prefix). Accept ≥0.70, else needs_review.
 * The embedding body is the fine-tuned e5-small, dynamic-int8 ONNX,
 * verified output-identical to the Python pipeline (6/6 suite).
 */

import { pipeline, env } from 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.5.2';

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = './';

const $ = (id) => document.getElementById(id);
const state = $('state'), dot = $('dot'), go = $('go');
const prog = $('prog'), progbar = $('progbar');

let extractor = null, rules = null, head = null, examples = null;

/* ---------- layer 1: rules ---------- */
function compileRules(raw) {
  const cats = {};
  for (const [cat, g] of Object.entries(raw.categories)) {
    cats[cat] = {
      strong: g.strong.map((p) => new RegExp(p, 'i')),
      weak: g.weak.map((p) => new RegExp(p, 'i')),
      negative: g.negative.map((p) => new RegExp(p, 'i')),
      // `assessment` and `follow_up` declare vetoes; the key is absent elsewhere.
      veto: (g.veto ?? []).map((p) => new RegExp(p, 'i')),
    };
  }
  return { cats, ats: raw.ats_domains };
}

function rulesClassify(subject, body, sender) {
  const scores = {};
  let isAts = false;
  if (sender && sender.includes('@')) {
    const dom = sender.toLowerCase().split('@').pop();
    isAts = rules.ats.some((a) => dom.includes(a));
  }
  for (const [cat, g] of Object.entries(rules.cats)) {
    let s = 0;
    for (const re of g.strong) { if (re.test(subject)) s += 6; else if (re.test(body)) s += 3; }
    for (const re of g.weak) { if (re.test(subject)) s += 2; else if (re.test(body)) s += 1; }
    for (const re of g.negative) { if (re.test(subject) || re.test(body)) s -= 5; }
    for (const re of g.veto) { if (re.test(subject) || re.test(body)) s = Math.min(s, 0); }
    scores[cat] = s;
  }
  const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const [winner, ws] = sorted[0];
  const runner = sorted[1] ? sorted[1][1] : 0;
  if (ws <= 0) return { category: 'other', confidence: 0.5 };
  const margin = ws - runner;
  let conf = 0.6;
  if (ws >= 10 && margin >= 5) conf = 0.95;
  else if (ws >= 6 && margin >= 3) conf = 0.9;
  else if (ws >= 4 && margin >= 2) conf = 0.8;
  else if (ws >= 2 && margin >= 1) conf = 0.7;
  if (isAts && ['applied', 'rejection', 'interview', 'offer'].includes(winner))
    conf = Math.min(conf + 0.05, 0.95);
  return { category: winner, confidence: conf };
}

/* ---------- embedding ---------- */
async function embed(text) {
  const out = await extractor(text, { pooling: 'mean', normalize: true });
  return Array.from(out.data);
}
const cosine = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0); // both normalized

/* ---------- layer 2: similarity ---------- */
function simClassify(vec) {
  let best = null, bestSim = -1;
  for (const ex of examples) {
    const s = cosine(vec, ex.vec);
    if (s > bestSim) { bestSim = s; best = ex.label; }
  }
  return { category: best, confidence: bestSim };
}

/* ---------- layer 3: setfit head ---------- */
function headClassify(vec) {
  const logits = head.coef.map((row, i) =>
    row.reduce((s, w, j) => s + w * vec[j], 0) + head.intercept[i]);
  const m = Math.max(...logits);
  const exps = logits.map((l) => Math.exp(l - m));
  const Z = exps.reduce((a, b) => a + b, 0);
  const probs = exps.map((e) => e / Z);
  const k = probs.indexOf(Math.max(...probs));
  return { category: head.classes[k], confidence: probs[k] };
}

/* ---------- UI ---------- */
const EXAMPLES = [
  ['Interview availability — SWE, Platform', "Hi Ayush, thanks for applying. We'd like to schedule a 45-minute technical interview next week. Could you share your availability?"],
  ['Your application was received', 'Thank you for applying to the Backend Engineer role. Our team is reviewing applications and will reach out if there is a match.'],
  ['Update on your application', "After careful consideration, we've decided to move forward with other candidates. We appreciate the time you invested."],
  ['Congratulations — offer details inside', "We're thrilled to extend an offer for the ML Engineer position. Compensation and start date are in the attached letter."],
  ['Next step: online assessment', 'Please complete the coding assessment linked below within 5 days. It should take about 90 minutes.'],
  ['Your weekly job digest', '12 new jobs recommended for you based on your profile. View all jobs or manage your preferences.'],
];

function renderTrace(rows) {
  $('trace').innerHTML = rows.map((r) =>
    `<div class="trow" data-state="${r.state}">
       <b>${r.layer}</b><span class="st">${r.note}</span>
       <span class="ms">${r.ms !== null ? r.ms.toFixed(1) + 'ms' : '—'}</span>
     </div>`).join('');
}

function renderVerdict(category, confidence, needsReview, source) {
  $('verdict').innerHTML =
    `<b>${category.replace(/_/g, ' ')}</b>
     <small>${(confidence * 100).toFixed(1)}% · answered by ${source}</small>
     ${needsReview ? '<small class="review">below 0.85 — production queues this for human review</small>' : ''}`;
}

async function classify() {
  const subject = $('subject').value.trim();
  const body = $('body').value.trim();
  if (!subject && !body) return;
  go.disabled = true;
  const trace = [];
  const t0 = performance.now();

  // layer 1 — rules
  const r1 = rulesClassify(subject, body, null);
  const t1 = performance.now();
  if (r1.confidence >= 0.9) {
    trace.push({ layer: 'rules', state: 'answered', note: `${r1.category} @ ${(r1.confidence * 100).toFixed(0)}% — regex answered`, ms: t1 - t0 });
    trace.push({ layer: 'embeddings', state: 'skipped', note: 'never ran', ms: null });
    trace.push({ layer: 'setfit', state: 'skipped', note: 'never ran', ms: null });
    renderVerdict(r1.category, r1.confidence, false, 'rules');
    renderTrace(trace); showTotal(t1 - t0); go.disabled = false; return;
  }
  trace.push({ layer: 'rules', state: 'passed', note: `top ${r1.category} @ ${(r1.confidence * 100).toFixed(0)}% — not confident enough`, ms: t1 - t0 });

  const text = `${subject} ${body}`.trim();

  // layer 2 — similarity (query-prefixed embedding)
  const tq0 = performance.now();
  const qvec = await embed('query: ' + text);
  const r2 = simClassify(qvec);
  const tq1 = performance.now();
  if (r2.confidence >= 0.85) {
    trace.push({ layer: 'embeddings', state: 'answered', note: `${r2.category} @ ${(r2.confidence * 100).toFixed(0)}% cosine`, ms: tq1 - tq0 });
    trace.push({ layer: 'setfit', state: 'skipped', note: 'never ran', ms: null });
    renderVerdict(r2.category, r2.confidence, false, 'embeddings');
    renderTrace(trace); showTotal(tq1 - t0); go.disabled = false; return;
  }
  trace.push({ layer: 'embeddings', state: 'passed', note: `best ${r2.category} @ ${(r2.confidence * 100).toFixed(0)}% — below 0.85`, ms: tq1 - tq0 });

  // layer 3 — setfit head (unprefixed embedding)
  const ts0 = performance.now();
  const svec = await embed(text);
  const r3 = headClassify(svec);
  const ts1 = performance.now();
  const needsReview = r3.confidence < 0.85;
  const category = r3.confidence >= 0.7 ? r3.category : 'needs_review';
  trace.push({ layer: 'setfit', state: 'answered', note: `${r3.category} @ ${(r3.confidence * 100).toFixed(0)}% softmax`, ms: ts1 - ts0 });
  renderVerdict(category, r3.confidence, needsReview, 'setfit');
  renderTrace(trace); showTotal(ts1 - t0); go.disabled = false;
}

function showTotal(ms) {
  $('timing').textContent = `total ${ms.toFixed(1)}ms · in this tab`;
}

async function boot() {
  renderTrace([
    // No number until rules.json is actually loaded, and then the number is
    // COUNTED from it (see the re-render below). This line used to hard-code
    // "201 patterns, ready" while the file it describes carried 212: no claim
    // site in scripts/readme_facts.py can anchor a number inside a template
    // literal, so the gate that keeps every other copy honest could not see it.
    { layer: 'rules', state: 'passed', note: 'loading patterns', ms: null },
    { layer: 'embeddings', state: 'passed', note: 'awaiting model', ms: null },
    { layer: 'setfit', state: 'passed', note: 'awaiting model', ms: null },
  ]);
  $('examples').innerHTML = EXAMPLES.map(([s], i) =>
    `<button class="ghost" data-i="${i}">${s.slice(0, 34)}…</button>`).join('');
  $('examples').addEventListener('click', (e) => {
    const i = e.target?.dataset?.i;
    if (i === undefined) return;
    $('subject').value = EXAMPLES[i][0];
    $('body').value = EXAMPLES[i][1];
    if (!go.disabled) classify();
  });
  go.addEventListener('click', classify);

  const [rulesRaw, headRaw, exRaw] = await Promise.all([
    fetch('./rules.json').then((r) => r.json()),
    fetch('./head.json').then((r) => r.json()),
    fetch('./examples.json').then((r) => r.json()),
  ]);
  rules = compileRules(rulesRaw); head = headRaw; examples = exRaw;

  // The scored count, derived from the file the page just compiled — the same
  // definition scripts/readme_facts.py uses (strong + weak + negative; vetoes
  // score nothing and stay outside the total).
  const ruleCount = Object.values(rulesRaw.categories).reduce(
    (n, g) => n + g.strong.length + g.weak.length + g.negative.length, 0);
  renderTrace([
    { layer: 'rules', state: 'passed', note: `${ruleCount} patterns, ready`, ms: null },
    { layer: 'embeddings', state: 'passed', note: 'awaiting model', ms: null },
    { layer: 'setfit', state: 'passed', note: 'awaiting model', ms: null },
  ]);

  prog.hidden = false;
  extractor = await pipeline('feature-extraction', 'model', {
    dtype: 'fp32',
    progress_callback: (p) => {
      if (p.status === 'progress' && p.total)
        progbar.style.width = `${Math.round((p.loaded / p.total) * 100)}%`;
    },
  });
  prog.hidden = true;

  await embed('warmup'); // JIT + session warm
  state.textContent = 'local · ready';
  dot.setAttribute('data-on', '');
  go.disabled = false;
}

boot().catch((err) => {
  state.textContent = 'failed to load';
  console.error(err);
});
