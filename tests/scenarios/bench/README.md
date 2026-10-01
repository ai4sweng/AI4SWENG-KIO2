# KIO2 measurement harness (D3.3 section 4.2)

Produces every figure quoted in D3.3 sections 4.2.1 and 4.2.4.

## Environment used for the reported figures

| | |
|---|---|
| Python | 3.11.15, Linux x86-64 |
| FocusTracer | 1.9.0 (`pip install -e` from github.com/BitnetTR/focustracer) |
| KIO2 | 1.0.6, called as a library, not through the container image |
| Trace schema | 2.3 |
| Recording budget | 45 s (`trace_timeout=45`), the value a dispatched step uses |
| Repetitions | median of 7 (sample programs), 5 (scaling), 3 (largest scaling size) |

## Layout expected by the scripts

```
bench/
  progs/    the four runnable programs of the test set (01..04)
  others/   the eleven files that do not parse
  fixed/    corrected copies of 01, 02, 04  (in this folder, copy to bench/fixed)
  scale/    created by the script
```

## Running

```bash
pip install -e <focustracer checkout>
pip install -e <AI4SWENG-KIO2 checkout>
python bench_recording.py       # M1 recording cost, M2 trace size, M4 reliability
python bench_localization.py    # M3 replay latency, M5 alignment, M6 localisation, M7 verdict
```

Results are written to `bench1.json` and `bench2.json`.

## Two additions to the test material, and why

**Corrected copies** (`fixed/`). The test set contains only faulty versions of each
program. Trace comparison needs a passing run of the same program, so a corrected
copy of 01, 02 and 04 was written. Each differs from its faulty counterpart by the
single planted fault and nothing else.

**Scaling program** (`scale/scaling.py`, generated). The four sample programs execute
between two and ten statements, so their runtime is entirely Python interpreter
startup and the cost of recording is invisible beneath it. A single counting loop with
the iteration count varied over four orders of magnitude separates the fixed cost of
recording from its marginal per-statement cost. This is what supports the figure
"0.2 s fixed plus 0.19 ms per recorded statement" rather than a meaningless ratio.

## Ground truth used for M6

| Program | Planted fault | Line | Starting point |
|---|---|---|---|
| 01 | `total += item['price']` moved out of the loop | 6 | criterion `10:total` |
| 02 | `user_db[0]` instead of `user_db[user_id]` | 4 | crash, no criterion |
| 04 | `balance >= amount` instead of `<` | 3 | criterion `5` |

Program 03 contains no planted fault and is the negative case for M7.

## Known gaps in what can be measured today

- The comparison output reports divergences as timeline index ranges with no source
  position, so "does the reported divergence fall on the planted fault line" cannot be
  computed. M5 reports distance and matched positions instead.
- Eleven of the fifteen files in the test set are not valid Python (IndentationError /
  SyntaxError), so the accuracy sample is three programs.
- The `inconclusive` verdict is not reached by any case in this material.

---

## Update, 23 September 2026: the full set

The eleven files under `others/` were not deliberately broken; their indentation was
destroyed by a copy-paste, which collapsed every level to one space and wrapped long
comment lines at column 0. Repaired copies are in `repaired/`. Only whitespace and the
wrapped comment lines were restored; no planted fault was touched. Each repaired file
was checked to behave exactly as its own `# HATA:` comment describes.

`bench_fullset.py` runs recording, localisation and verdict over all fifteen programs
and writes `results_fullset.json`. Ground truth and starting point per program:

| Program | Planted fault | Line | Fails by | Starting point |
|---|---|---|---|---|
| 01 | statement moved out of the loop | 6 | silent | criterion `10:total` |
| 02 | wrong dictionary key | 4 | KeyError | crash |
| 03 | none | — | — | — |
| 04 | inverted comparison | 3 | silent | criterion `5` |
| 05 | release logic left empty | 13 | RuntimeError | crash |
| 06 | no type check before `.strip()` | 4 | AttributeError | crash |
| 07 | wrong recursion base case | 4 | RecursionError | crash |
| 08 | none | — | — | — |
| 09 | comparison operator reversed | 6 | silent | criterion `8` |
| 10 | off-by-one loop bound | 5 | IndexError | crash |
| 11 | assignment shadows the global | 8 | UnboundLocalError | crash |
| 12 | none | — | — | — |
| 13 | `==` used instead of `=` | 5 | silent | criterion `7:user_profile` |
| 14 | mutable default argument | 3 | silent | criterion `7:result_list` |
| 15 | dict mutated while iterating | 6 | RuntimeError | crash |

### Results on the full set

- Recording: 15 of 15 produced a schema-valid trace within the 45 s budget.
- Localisation: planted line ranked first in 3 of 12, present in the ranking in 6 of 12.
- Verdict: 17 of 18 correct (15 programs plus 3 corrected copies, minus overlap).

### Two defects found while measuring

1. **Recording stops at a call depth of 100 frames** and the truncation is not marked.
   Program 07 fails only far below that depth, so its trace ends with no exception in
   it, and KIO2 reports `clean` with confidence 1.0 for a run that crashes. A truncated
   recording should be flagged, and the verdict should be `inconclusive`, not `clean`.
2. **Control dependency is structural**, taken from the nearest enclosing conditional or
   loop. In program 09 the deciding condition does not lexically enclose the criterion,
   so the fault is not reached. Post-dominator analysis would find it.

### Four faults that trace-based localisation cannot reach by construction

05 (omission), 13 (statement with no effect), 14 (evaluated at definition time),
11 (statement never executed). These should be stated as out of scope rather than
counted as misses.
