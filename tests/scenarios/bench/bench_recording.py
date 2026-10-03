import json
import os
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from kio2.runner import run_trace

REPS = 7
OUT = {}


def med_native(script, cwd, reps=REPS):
    ts = []
    for _ in range(reps):
        t = time.perf_counter()
        subprocess.run([sys.executable, script], cwd=cwd, capture_output=True)
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts)


def med_traced(script, cwd, reps=REPS):
    ts = []
    path = None
    for _ in range(reps):
        t = time.perf_counter()
        path = run_trace(script, working_directory=cwd, timeout=45)
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts), path


def stats(xml_path):
    r = ET.parse(xml_path).getroot()
    s = r.find("./metadata/statistics")

    def g(k):
        return int(s.findtext(k, "0"))

    return dict(
        total=g("total_events"),
        lines=g("line_count"),
        calls=g("call_count"),
        bytes=os.path.getsize(xml_path),
        schema=r.get("schema_version"),
    )


# ---------- M1 / M2 : sample programs ----------
rows = []
for name in sorted(os.listdir("progs")):
    if not name.endswith(".py"):
        continue
    nat = med_native(name, "/tmp/bench/progs")
    tr, path = med_traced(name, "/tmp/bench/progs")
    st = stats(path)
    rows.append(
        dict(
            prog=name[:2],
            native_ms=round(nat, 1),
            traced_ms=round(tr, 1),
            ratio=round(tr / nat, 1),
            lines=st["lines"],
            bytes=st["bytes"],
            bytes_per_line=round(st["bytes"] / st["lines"], 1),
            schema=st["schema"],
            trace=path,
        )
    )
OUT["sample"] = rows

# ---------- M1 / M2 : scaling, to separate fixed cost from marginal cost ----------
scale = []
for N in (100, 1000, 10000, 50000):
    src = f"""def work(n):
    total = 0
    for i in range(n):
        total = total + i
    return total
print(work({N}))
"""
    d = Path("/tmp/bench/scale")
    d.mkdir(exist_ok=True)
    for old in d.glob("*.py"):
        old.unlink()
    f = d / "scaling.py"
    f.write_text(src)
    reps = 5 if N < 50000 else 3
    nat = med_native("scaling.py", str(d), reps)
    tr, path = med_traced("scaling.py", str(d), reps)
    st = stats(path)
    scale.append(
        dict(
            N=N,
            native_ms=round(nat, 1),
            traced_ms=round(tr, 1),
            ratio=round(tr / nat, 1),
            lines=st["lines"],
            bytes=st["bytes"],
            bytes_per_line=round(st["bytes"] / st["lines"], 1),
        )
    )
OUT["scale"] = scale

# ---------- M4 : reliability over every program in the set ----------
rel = []
for folder in ("progs", "others"):
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".py"):
            continue
        rec = dict(prog=name, folder=folder)
        try:
            t = time.perf_counter()
            p = run_trace(name, working_directory=f"/tmp/bench/{folder}", timeout=45)
            rec["ok"] = True
            rec["ms"] = round((time.perf_counter() - t) * 1000, 1)
            rec["lines"] = stats(p)["lines"]
        except Exception as e:
            rec["ok"] = False
            rec["reason"] = f"{type(e).__name__}: {str(e)[:160]}"
        rel.append(rec)
OUT["reliability"] = rel

json.dump(OUT, open("bench1.json", "w"), indent=1)
print(json.dumps({k: OUT[k] for k in ("sample", "scale")}, indent=1))
print("reliability:", sum(1 for r in rel if r["ok"]), "/", len(rel))
for r in rel:
    if not r["ok"]:
        print("  FAIL", r["folder"] + "/" + r["prog"], r["reason"][:110])
