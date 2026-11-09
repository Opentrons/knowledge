# Retrieval Experiments: What We Tried and Why We Ship What We Ship

Corpus: `10.0.0-k3` (docs `mkdocs-2026-09-30` @ `00f1431b`, Protocol API and
shared-data `v10.0.0` @ `e8c6d0a4`, AI guides `ai-server@0.0.22`).
Report: `reports/retrieval-eval.json` in the corpus. Re-run with
`just retrieval-experiment`. The design is in
[retrieval-design.md](retrieval-design.md).

## Result

The docs index is **narrative sections plus shared-data entities, structured
chunking, heading-path context plus identifier terms, BM25 with Tantivy's default
tokenizer**. The baseline in the table is one chunk per section, no context,
docs plus AI guides, rebuilt on the same canonical docs. Compared with that,
the docs index improves curated MRR@10 from 0.501 to 0.601 (+0.100, 95% CI
+0.035 to +0.163). It also raises structural Hit@10 from 0.533 to 0.975, at
the same index size and latency:

Symbol reference sections are not in this index. They ship in `retrieval/api/`,
where each public name is an exact token. That split is measured by
`retrieval audit` (every documented symbol must come back first), not by the
curated how-to questions below.

| | One chunk per section (baseline) | Docs index |
|---|---:|---:|
| Curated MRR@10 | 0.501 | **0.601** |
| Curated Hit@1 / Hit@5 / Hit@10 | 0.362 / 0.724 / 0.800 | **0.448 / 0.838 / 0.886** |
| Structural Hit@10 | 0.533 | **0.975** |
| Chunks | 2129 | 2088 |
| Index size | 1.7 MB | 1.6 MB |
| Build time / p50 query latency | 0.11 s / 0.15 ms | 0.15 s / 0.15 ms |

Four findings drive the choice, in order of effect size:

1. **Index shared-data entities.** This is the largest single gain. Labware
   questions ("load name for the NEST 96 well PCR plate") have no answer in
   prose; the load name lives only in shared-data. Removing entities costs
   0.051 MRR overall (95% CI +0.006 to +0.101). Labware MRR drops from 0.592
   to 0.178, and structural labware-name Hit@10 drops from 1.0 to 0.
2. **Prefix the heading path.** A canonical section's body does not contain its
   own heading, and the heading is usually the most specific text in the
   section. Removing the context prefix costs 0.059 MRR (CI +0.024 to +0.099)
   and drops structural Hit@10 from 0.975 to 0.804. Adding split camelCase
   identifiers and aliases on top adds a further 0.022 (CI +0.001 to +0.048).
3. **Never use fixed windows.** Word windows that ignore structure are the worst
   strategy everywhere: 0.178 MRR below the winner (CI +0.105 to +0.246). They
   cut sections mid-thought, mix unrelated topics into one chunk, and lose the
   headings that finding 2 shows matter.
4. **Do not index API symbols or AI guides alongside the docs.** Neither helps,
   and both add near-duplicate or lower-authority text that competes for the
   top slots (details below).

## Method

### Evaluation set

- **Curated: 105 questions** in `eval/retrieval/curated.yaml`, written the way
  users and OpentronsAI ask, deliberately not copying heading text. There are 9
  categories: protocol API (40), labware (15), modules (13), hardware (13), app
  and software (11), Protocol Designer (5), maintenance (5), and compliance (3).
  Status: **draft, awaiting docs-owner review.**
- **Structural: 240 queries** generated from the documents. They are 100
  section titles (unique titles only), 80 API member names, and 60 labware
  display names, each labeled with its own record. Their answers are objective,
  but BM25 finds them easily, so they act only as a guard, never as the primary
  metric.

Labels name answers independently of chunking. `doc:<page>#<anchor>` accepts
that section or any section nested under it; `api:<name>` accepts the reference
section or the symbol record. Labels are resolved against the full document
set, so a configuration that leaves a kind out of its index is scored on the
same answers and simply misses them. A label that resolves to nothing fails the
run, so stale labels cannot silently score zero.

### Metrics

A query hits at rank *k* when any acceptable retrieval id is among the first *k*
distinct ids returned. Chunk hits are expanded to the documents they cover, in
order, so a window covering three sections contributes three ranks. We report
Hit@1, 3, 5, and 10 and MRR@10, overall, per source, and per category. nDCG was
dropped: labels list acceptable alternatives, not graded or exhaustive
judgments, so nDCG would penalize configurations for not returning every
acceptable section.

Differences are tested with a paired bootstrap over the curated queries (2000
resamples, seeded, so the report reproduces exactly). With 105 queries a
difference under about 0.02 MRR is noise.

### Decision rule (fixed before the grid ran)

> Among configurations whose returned text is the passage a reader sees
> (default tokenizer, not 80-word fragments), pick the highest curated MRR@10.
> Configurations within 0.01 of the best are tied; break ties by curated Hit@5,
> then by simplicity (fewer chunking and enrichment steps, fewer record kinds).
> The winner's structural Hit@10 may not fall more than 0.02 below the
> baseline's.

`small` chunking is excluded because a hit has to be readable on its own, not
an 80-word fragment the caller must expand. `en_stem` is excluded because it
did not win and it changes which word forms a query must use. Both were still
measured.

### Grid

51 configurations: the baseline, plus 4 compositions by 4 chunking strategies by
3 enrichments, plus 2 stemming variants. The whole grid builds and scores in
about 12 seconds, so it runs on every corpus build. If a new release would
select a different winner, the build logs a warning and records both in
`retrieval/manifest.json`.

## Ablations

Each row changes one factor of the winner. A positive delta means the winner is
better.

| Change from the winner | Curated MRR@10 delta | 95% CI | Reading |
|---|---:|---|---|
| Baseline (one chunk per section) | +0.100 | [+0.035, +0.163] | Clear win. |
| Remove entities | +0.051 | [+0.006, +0.101] | Entities matter. |
| Context terms to plain | +0.059 | [+0.024, +0.099] | Context matters. |
| Context terms to context only | +0.022 | [+0.001, +0.048] | Identifier terms help a little. |
| Structured to section | -0.007 | [-0.029, +0.015] | Tie. |
| Structured to small | +0.015 | [-0.022, +0.053] | Tie, and the fragment is not what we return. |
| Structured to window | +0.178 | [+0.105, +0.246] | Windows are much worse. |
| Add API symbols | +0.013 | [+0.004, +0.026] | Symbols hurt slightly. |
| Add symbols and AI guides | +0.034 | [-0.006, +0.071] | Probably hurts; not significant. |
| Add symbols and guides, `en_stem` | +0.036 | [-0.021, +0.092] | Stemming does not help (0.565 vs 0.567 unstemmed). |

### Structured or one chunk per section?

They are statistically tied (CI spans zero). Three configurations landed within
0.01 of the best. The pre-registered tie-break (curated Hit@5) picked
`structured`: 0.838 versus 0.829, which is a single question. We keep it for a
practical reason as well: `structured` emits each Flex and OT-2 tab as its own
chunk with the tab label in its context, so a robot-specific question returns
the procedure for that robot instead of a section that interleaves both. It
costs 9% more chunks (2088 versus 1916).

### Why API symbols hurt

The Python API reference pages are already in `canonical/`: mkdocstrings renders
the same docstrings, signatures, and version notes into `doc_section` records
with `api_name` set. Adding the AST symbol records on top puts near-identical
duplicates in the index. They crowd other answers out of the top ranks. Those
reference sections are the API index. The AST records stay out of both indexes.

### Why AI guides are left out

The guides are long, pattern-oriented, and `curated_guidance`, below official
docs in the authority order. In this set they act mostly as distractors: adding
them alongside symbols costs 0.034 MRR, though the interval crosses zero. Only 4
curated questions name a guide as an acceptable answer, so this measures guides
as competition, not as answers. Revisit this once reviewed questions target
guide-only knowledge (for example, the out-of-tips index error guide).

### Why not stem?

Stemming changes every query: `loading` and `load` would match, and so would
unrelated forms. It had to beat the unstemmed index to be worth that. It did
not: 0.565 stemmed versus 0.567 unstemmed on the same composition and chunking.
It fixes a few misses ("weigh" and "weight") and causes as many.

## Where the winner still fails

17 of 105 curated questions miss the top 5. Most are **vocabulary mismatch**,
which BM25 cannot bridge and dense retrieval should:

| Question | Expected | What ranked first |
|---|---|---|
| install the Opentrons App on Linux | `#ubuntu` sections | first-run USB setup |
| how much does the Flex weigh and how big is it | general specifications | API overview |
| put the tip back in the rack instead of throwing it away | `#returning-a-tip` | partial tip pickup |
| robot hit an error mid-run, how do I recover | touchscreen error recovery | OT-2 factory reset |
| change how fast the pipette aspirates in microliters per second | flow rates | Protocol Designer pipette path |

The other pattern is **long code-heavy pages outranking the specific section**.
For example, `python-api/examples/` ranks above the pipette-loading section for
"load a pipette on the left mount", because every example repeats
`load_instrument`.

These misses are the target set for the next experiment: adding a dense index
with RRF, measured on this same evaluation set.

## Reproduce

```bash
just build-10-0-0-k3          # builds the corpus, retrieval/, and reports/retrieval-eval.json
just retrieval-experiment     # re-runs the grid; writes dist/retrieval-eval.{json,md}
just retrieval-search "load a 96 channel pipette"
```

The full 51-row table is in `dist/retrieval-eval.md` after
`just retrieval-experiment`, and in `reports/retrieval-eval.json` under
`results`.
