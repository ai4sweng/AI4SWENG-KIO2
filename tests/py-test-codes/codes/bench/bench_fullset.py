import json, os, statistics, subprocess, sys, time
import xml.etree.ElementTree as ET
from kio2 import Kio2Input, localize
from kio2.runner import run_trace
from kio2.kio1 import localization_output

ROOT='/tmp/bench/all'
CASES = {
 '01': dict(crashes=False, gt=6,  crit='10:total',           fault='statement moved out of the loop'),
 '02': dict(crashes=True,  gt=4,  crit=None,                 fault='wrong dictionary key'),
 '03': dict(crashes=False, gt=None,crit=None,                fault=None),
 '04': dict(crashes=False, gt=3,  crit='5',                  fault='inverted comparison'),
 '05': dict(crashes=True,  gt=13, crit=None,                 fault='release logic left empty'),
 '06': dict(crashes=True,  gt=4,  crit=None,                 fault='no type check before .strip()'),
 '07': dict(crashes=True,  gt=4,  crit=None,                 fault='wrong recursion base case'),
 '08': dict(crashes=False, gt=None,crit=None,                fault=None),
 '09': dict(crashes=False, gt=6,  crit='8',                  fault='comparison operator reversed'),
 '10': dict(crashes=True,  gt=5,  crit=None,                 fault='off-by-one loop bound'),
 '11': dict(crashes=True,  gt=8,  crit=None,                 fault='assignment shadows the global'),
 '12': dict(crashes=False, gt=None,crit=None,                fault=None),
 '13': dict(crashes=False, gt=5,  crit='7:user_profile',     fault='== used instead of ='),
 '14': dict(crashes=False, gt=3,  crit='7:result_list',      fault='mutable default argument'),
 '15': dict(crashes=True,  gt=6,  crit=None,                 fault='dict mutated while iterating'),
}
files = {n[:2]: n for n in sorted(os.listdir(ROOT)) if n.endswith('.py')}
REPS=7
def stats(p):
    r=ET.parse(p).getroot(); s=r.find('./metadata/statistics')
    return int(s.findtext('line_count','0')), os.path.getsize(p), r.get('schema_version')

OUT={}
# M1/M2/M4
rows=[]
for k in sorted(files):
    f=files[k]
    nat=[]; tr=[]; path=None; err=None
    for _ in range(REPS):
        t=time.perf_counter(); subprocess.run([sys.executable,f],cwd=ROOT,capture_output=True); nat.append((time.perf_counter()-t)*1000)
    try:
        for _ in range(REPS):
            t=time.perf_counter(); path=run_trace(f,working_directory=ROOT,timeout=45); tr.append((time.perf_counter()-t)*1000)
        ln,by,sv=stats(path)
        rows.append(dict(p=k, ok=True, native=round(statistics.median(nat),1), traced=round(statistics.median(tr),1),
                         lines=ln, bytes=by, bpl=round(by/ln,1), schema=sv))
    except Exception as e:
        rows.append(dict(p=k, ok=False, reason=f"{type(e).__name__}: {str(e)[:100]}"))
OUT['record']=rows

# M6 + M7
loc=[]; verd=[]
for k in sorted(files):
    c=CASES[k]; f=files[k]
    r=localize(Kio2Input(target_script=f, working_directory=ROOT, criterion=c['crit'], trace_timeout=45))
    out=localization_output(r, root=ROOT)
    v=out.get('verdict')
    expect='clean' if c['gt'] is None else 'defect'
    verd.append(dict(p=k, expect=expect, verdict=v, n=len(out.get('findings') or []), ok=(v==expect), status=r.status))
    if c['gt'] is not None:
        rank=next((s.rank for s in r.suspect_lines if s.line==c['gt']), None)
        dep=next((s.dependency for s in r.suspect_lines if s.line==c['gt']), None)
        loc.append(dict(p=k, fault=c['fault'], start=('crash' if c['crit'] is None else 'criterion '+c['crit']),
                        gt=c['gt'], rank=rank, dep=dep, n=len(r.suspect_lines),
                        conf=round(r.confidence,2),
                        ranking=[(s.rank,s.line,s.dependency,round(s.score,2)) for s in r.suspect_lines]))
OUT['localize']=loc; OUT['verdict']=verd
json.dump(OUT, open('bench3.json','w'), indent=1, default=str)

print("== recording ==")
for r in rows:
    print(" ", r['p'], "ok" if r['ok'] else "FAIL", r.get('native'), r.get('traced'), "lines=",r.get('lines'), "bpl=",r.get('bpl'), r.get('reason',''))
print("== localisation ==")
for r in loc:
    print(f"  {r['p']} gt={r['gt']:>3} rank={str(r['rank']):>4} of {r['n']:>2}  dep={r['dep']}  start={r['start']}  ({r['fault']})")
hits=[r['rank'] for r in loc]
for k in (1,5,10):
    print(f"  top-{k}: {sum(1 for h in hits if h and h<=k)}/{len(hits)}")
print("  not found:", sum(1 for h in hits if h is None))
print("== verdict ==")
print("  correct", sum(1 for v in verd if v['ok']), "/", len(verd))
for v in verd:
    if not v['ok']: print("   MISS", v)
