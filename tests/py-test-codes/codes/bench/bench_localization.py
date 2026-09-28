import json
import statistics
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from kio2 import AlignInput, Kio2Input, ReplayInput, compare, localize, replay
from kio2.kio1 import localization_output
from kio2.runner import run_trace

OUT = {}


def lines_of(p):
    return int(ET.parse(p).getroot().findtext("./metadata/statistics/line_count", "0"))


# ---------- M3 : replay / navigation latency ----------
d = Path("/tmp/bench/scale")
d.mkdir(exist_ok=True)
(d / "scaling.py").write_text(
    "def work(n):\n    total = 0\n    for i in range(n):\n        total = total + i\n    return total\nprint(work(1000))\n"
)
big = run_trace("scaling.py", working_directory=str(d), timeout=45)
small = run_trace(
    "01_siparis_toplami_hesaplama.py", working_directory="/tmp/bench/progs", timeout=45
)


def replay_timings(trace, n_positions):
    load = []
    from focustracer.core.loader import TraceLoader

    for _ in range(5):
        t = time.perf_counter()
        TraceLoader().load(trace)
        load.append((time.perf_counter() - t) * 1000)
    fwd = []
    back = []
    step = max(1, n_positions // 40)
    for seq in range(1, n_positions, step):
        t = time.perf_counter()
        replay(ReplayInput(trace_path=trace, seq=seq, step=1))
        fwd.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        replay(ReplayInput(trace_path=trace, seq=seq, step=-1))
        back.append((time.perf_counter() - t) * 1000)
    return dict(
        load_ms=round(statistics.median(load), 1),
        fwd_call_ms=round(statistics.median(fwd), 1),
        back_call_ms=round(statistics.median(back), 1),
        samples=len(fwd),
    )


OUT["replay"] = {
    "small_trace": dict(lines=lines_of(small), **replay_timings(small, lines_of(small))),
    "large_trace": dict(lines=lines_of(big), **replay_timings(big, lines_of(big))),
}

# ---------- M5 : alignment of failing vs passing run ----------
GT = {"01": 6, "02": 4, "04": 3}
align_rows = []
for k, fname in (
    ("01", "01_siparis_toplami_hesaplama.py"),
    ("02", "02_kullanici_profil_guncelleme.py"),
    ("04", "04_banka_hesabi_para_cekme.py"),
):
    tb = run_trace(fname, working_directory="/tmp/bench/progs", timeout=45)
    tf = run_trace(fname, working_directory="/tmp/bench/fixed", timeout=45)
    c = compare(AlignInput(trace_paths=[tb, tf]))
    divs = c.divergences or []
    first_lines = []
    for dv in divs[:4]:
        first_lines.append(
            {
                kk: dv.get(kk)
                for kk in ("a_line", "b_line", "kind", "a_seq", "b_seq", "reason")
                if kk in dv
            }
        )
    align_rows.append(
        dict(
            prog=k,
            status=c.status,
            mode=c.mode,
            distance=c.distance,
            norm=round(c.normalized_distance, 3),
            matched=c.matched,
            gaps=c.gaps,
            n_div=len(divs),
            first_divs=first_lines,
            gt_line=GT[k],
            raw0=divs[0] if divs else None,
        )
    )
OUT["align"] = align_rows

# ---------- M6 : localisation accuracy ----------
CASES = [
    dict(
        prog="01",
        script="01_siparis_toplami_hesaplama.py",
        criterion="10:total",
        gt=6,
        crashes=False,
    ),
    dict(prog="02", script="02_kullanici_profil_guncelleme.py", criterion=None, gt=4, crashes=True),
    dict(prog="04", script="04_banka_hesabi_para_cekme.py", criterion="5", gt=3, crashes=False),
]
loc = []
for c in CASES:
    r = localize(
        Kio2Input(
            target_script=c["script"],
            working_directory="/tmp/bench/progs",
            criterion=c["criterion"],
            trace_timeout=45,
        )
    )
    ranks = [
        (s.rank, s.line, s.dependency, round(s.score, 2), s.source.strip()[:50])
        for s in r.suspect_lines
    ]
    hit = next((s.rank for s in r.suspect_lines if s.line == c["gt"]), None)
    loc.append(
        dict(
            prog=c["prog"],
            criterion_given=c["criterion"],
            status=r.status,
            criterion=r.criterion,
            confidence=round(r.confidence, 2),
            slice_size=r.slice_size,
            gt_line=c["gt"],
            gt_rank=hit,
            n=len(ranks),
            ranking=ranks,
        )
    )
OUT["localize"] = loc

# ---------- M7 : verdict ----------
verd = []
for label, folder, script, crit, expect in [
    ("01 buggy", "progs", "01_siparis_toplami_hesaplama.py", "10:total", "defect"),
    ("02 buggy", "progs", "02_kullanici_profil_guncelleme.py", None, "defect"),
    ("03 clean", "progs", "03_sicaklik_degerleri_ortalamasi.py", None, "clean"),
    ("04 buggy", "progs", "04_banka_hesabi_para_cekme.py", "5", "defect"),
    ("01 fixed", "fixed", "01_siparis_toplami_hesaplama.py", None, "clean"),
    ("02 fixed", "fixed", "02_kullanici_profil_guncelleme.py", None, "clean"),
    ("04 fixed", "fixed", "04_banka_hesabi_para_cekme.py", None, "clean"),
]:
    r = localize(
        Kio2Input(
            target_script=script,
            working_directory=f"/tmp/bench/{folder}",
            criterion=crit,
            trace_timeout=45,
        )
    )
    out = localization_output(r, root=f"/tmp/bench/{folder}")
    verd.append(
        dict(
            case=label,
            expect=expect,
            verdict=out.get("verdict"),
            defect_found=out.get("defect_found"),
            status=r.status,
            n_findings=len(out.get("findings") or []),
            match=(out.get("verdict") == expect),
        )
    )
OUT["verdict"] = verd

json.dump(OUT, open("bench2.json", "w"), indent=1, default=str)
print(json.dumps(OUT, indent=1, default=str)[:6000])
