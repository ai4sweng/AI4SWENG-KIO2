# Test scenarios

Fifteen small Python programs, each with one planted bug. The bugs are the test
data, so the files must stay as written (they are excluded from linting).
[`focustracer_test_scenarios.pdf`](focustracer_test_scenarios.pdf) describes
every scenario and its expected behaviour.

They are not part of the pytest suite. Use them to try KIO2 by hand.

## Two kinds of bug

KIO2 localises a fault from an error raised at run time. A program that ends
normally with a wrong result gives it nothing to start from, so it reports
`clean`.

| Raises an error: KIO2 localises it | Wrong result, no error: KIO2 reports `clean` |
|---|---|
| 02 `KeyError` | 01, 03, 04 |
| 05 `RuntimeError` | 08, 09 |
| 06 `AttributeError` | 12, 13, 14 |
| 10 `IndexError` | |
| 11 `UnboundLocalError` | |
| 15 `RuntimeError` | |

07 (`RecursionError`) is a special case: the recursion is deep enough to stop
the recording before the error is written, so KIO2 answers `inconclusive` and
asks for human review instead of localising it.

`01_fixed_siparis_toplami_hesaplama.py` is a corrected version of 01, useful as
a passing run to compare with.

## Try one

With KIO2 running (see the main [README](../../README.md)), open
`http://127.0.0.1:8102/docs`, choose **POST /execute** and send:

```json
{
  "workflow_id": "wf-try",
  "step_id": "s1",
  "capability": "bug_localization",
  "data": {
    "repository": { "path": "<absolute path to this folder>" },
    "target": { "entry_point": "10_dizi_elemanlari_farki.py" }
  }
}
```

The first finding is line 6 of `calculate_adjacent_differences`, where
`numbers[i+1]` runs past the end of the list.

## Other folders

- `bench/`: the measurement scripts and results reported in D3.3. See its
  [README](bench/README.md).
- `output/`: traces you record by hand. Ignored by git.
