# AI-assisted code (Claude / Codex / ChatGPT), reviewed and run by Team ULAK.
"""Independent re-computation of the three headline findings.
Does NOT import timeseries.py or reference_data.py: numpy + pyproj only, reads raw cache + reference text."""
import glob, json, sys, numpy as np
from pyproj import Transformer
EXCL={'2026-10-06'}
files=sorted(glob.glob('data/derived/cache/*.npz'))
def lab_blocks(fn):
    out={};cur=None
    for l in open(fn).read().splitlines():
        if l.startswith('#'): cur=l[1:].strip(); out[cur]=[]
        elif l.strip(): out[cur].append(l.strip())
    return out
dec=lambda rows: np.array([[ord(c)-97 for c in r] for r in rows],float)
iv={k.split()[1]:dec(v)/25 for k,v in lab_blocks('data/reference/dswx_s1_iv_cells.txt').items()}
ow={k.split()[1]:dec(v)/25 for k,v in lab_blocks('data/reference/dswx_s1_ow_cells.txt').items()}
reg=lab_blocks('data/reference/modis_regions_cells.txt')
sav=dec(reg['SAV4'])*4
cen=[float(x) for x in [k for k in reg if k.startswith('CENTRE')][0].split(' ',1)[1].split(',')]
cells={}
grid=None
for f in files:
    d=f.split('/')[-1][:10]
    if d in EXCL: continue
    z=np.load(f); m=z['mask']; ok=(m!=0)&(m!=255)
    if grid is None:
        x,y=z['x'],z['y']; X,Y=np.meshgrid(x,y)
        lon,lat=Transformer.from_crs('EPSG:32636','EPSG:4326',always_xy=True).transform(X,Y)
        c=np.floor((lon-30.55)/0.01).astype(int); r=np.floor((7.40-lat)/0.01).astype(int)
        inside=(c>=0)&(c<40)&(r>=0)&(r<40); grid=(r,c,inside)
    r,c,inside=grid
    cells[d]={}
    for term in ('HHHH','HVHV'):
        if 'term_'+term not in z.files: continue
        a=z['term_'+term].astype('float64'); v=ok&inside&np.isfinite(a)&(a>=0)
        s=np.zeros((40,40));n=np.zeros((40,40))
        np.add.at(s,(r[v],c[v]),a[v]);np.add.at(n,(r[v],c[v]),1)
        mean=np.where(n>=1250,s/np.maximum(n,1),np.nan)   # >=1250 of ~3000 20 m px
        cells[d][term]=10*np.log10(mean)
dates=sorted(cells); print('dates',dates)
import datetime as dt
match={d:(dt.date.fromisoformat(d)-dt.timedelta(days=1)).isoformat() for d in dates}
md=[d for d in dates if match[d] in iv]; print('matched',[(d,match[d]) for d in md])
IV=np.stack([iv[match[d]] for d in md]); OW=np.stack([ow[match[d]] for d in md]); W=IV+OW
strata={'inundated_veg':np.all(IV>=0.5,0),'open_water':np.all(OW>=0.5,0),'not_water':np.all(W<=0.05,0)}
rng=np.random.default_rng(7)
def ci(v):
    v=v[np.isfinite(v)]; b=np.median(v[rng.integers(0,v.size,(4000,v.size))],1)
    return round(float(np.median(v)),2),round(float(np.quantile(b,.025)),2),round(float(np.quantile(b,.975)),2),int(v.size)
res={}
for term,d0,d1 in (('HHHH',dates[0],dates[-1]),('HVHV',dates[0],dates[-1])):
    D=cells[d1][term]-cells[d0][term]
    for s,m in strata.items(): res[f'{term}:{s}']=ci(D[m]); print(term,s,'cells',int(m.sum()),'median,lo,hi,n',res[f'{term}:{s}'])
# difference IV - not water
D=cells[dates[-1]]['HHHH']-cells[dates[0]]['HHHH']
a=D[strata['inundated_veg']];b=D[strata['not_water']];a=a[np.isfinite(a)];b=b[np.isfinite(b)]
bd=np.median(a[rng.integers(0,a.size,(4000,a.size))],1)-np.median(b[rng.integers(0,b.size,(4000,b.size))],1)
print('HH IV minus not-water: %.2f [%.2f, %.2f]'%(np.median(a)-np.median(b),*np.quantile(bd,[.025,.975])))
# superblock (3x3 cells) bootstrap to respect spatial correlation
sb=(np.arange(40)[:,None]//3)*100+(np.arange(40)[None,:]//3)
def sbci(D,m1,m2):
    ids=np.unique(sb); out=[]
    for _ in range(2000):
        pick=rng.choice(ids,ids.size); 
        w=np.zeros(ids.max()+1); np.add.at(w,pick,1); ww=w[sb]
        x=np.repeat(D[m1&np.isfinite(D)],ww[m1&np.isfinite(D)].astype(int)); yv=np.repeat(D[m2&np.isfinite(D)],ww[m2&np.isfinite(D)].astype(int))
        if x.size>3 and yv.size>3: out.append(np.median(x)-np.median(yv))
    return np.quantile(out,[.025,.975])
print('  superblock(3x3 cell) CI for IV - not-water:',np.round(sbci(D,strata['inundated_veg'],strata['not_water']),2))
# time course per stratum
for s,m in strata.items(): print(s,'HH change by date',[(d[5:],round(float(np.nanmedian((cells[d]['HHHH']-cells[dates[0]]['HHHH'])[m])),2)) for d in dates])
# baseline levels
for s,m in strata.items(): print(s,'HH level first/last',round(float(np.nanmedian(cells[dates[0]]['HHHH'][m])),1),round(float(np.nanmedian(cells[dates[-1]]['HHHH'][m])),1),'HV',round(float(np.nanmedian(cells[dates[0]]['HVHV'][m])),1),round(float(np.nanmedian(cells[dates[-1]]['HVHV'][m])),1))
# distance profile, savanna >=80%
dist=np.array([[(cc+0.5-cen[rr])*1.104 for cc in range(40)] for rr in range(40)])
for term in ('HHHH','HVHV'):
    D=cells[dates[-1]][term]-cells[dates[0]][term]
    print(term,'distance profile (bin start km, median, lo, hi, n):')
    for b0 in range(-22,22,4):
        m=(sav>=80)&(dist>=b0)&(dist<b0+4)&np.isfinite(D)
        if m.sum()>=5: print('   ',b0,ci(D[m]))
# where are IV strata cells relative to margins? overlap
lab=np.array([list(r) for r in reg['LABEL']])
for s,m in strata.items(): print(s,'by MODIS region',{k:int((m&(lab==k)).sum()) for k in 'CWE.'}, 'median |dist| km',round(float(np.median(np.abs(dist[m]))),1))

# --- adversarial check: is the stratum contrast only a "dark pixels brighten more" effect?
h0=cells[dates[0]]['HHHH']; D=cells[dates[-1]]['HHHH']-h0
print('Baseline-matched comparison (20 Jun HH level bins, dB): IV-stratum vs all other cells')
for lo,hi in ((-13,-11),(-11,-9),(-9,-7)):
    a=strata['inundated_veg']&(h0>=lo)&(h0<hi)&np.isfinite(D); b=~strata['inundated_veg']&~strata['open_water']&(h0>=lo)&(h0<hi)&np.isfinite(D)
    if a.sum()>=5 and b.sum()>=5: print('   bin',lo,hi,'IV',ci(D[a]),'other',ci(D[b]))
