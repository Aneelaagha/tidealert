"""Diagnostics for the FIM-driven isolation backtest on White Oak Bayou (USGS 08074500).

Answers four questions about why no block-group zone became isolated:

  Q1  What fraction of road segments flood at peak stage, by denominator, and
      does the FIM extent agree with 3DEP ground elevation (i.e. is the
      stage -> extent conversion sane)?
  Q2  How large are the zones, and does isolation appear at census-block
      ("last mile") scale? Q2b splits isolated blocks into dry-but-cut-off vs
      submerged.
  Q3  Exact (15-minute) crossing times of each signal vs the gauge
      flood-stage alarm, instead of hourly steps.
  Q4  How many roads crossing each zone boundary ("entry roads") flood.

Prerequisites are the same as scripts/backtest_isolation.py.

Usage (from the repo root):
    .venv/bin/python scripts/diagnose_isolation.py
"""
import sys; sys.path.insert(0,'backend')
from datetime import datetime, timezone, timedelta
import numpy as np, geopandas as gpd, requests, networkx as nx, rasterio
from shapely.geometry import Point, box
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Zone
from app.services import stage as st, isolation_engine as ie
D="backend/app/data/"; CDT=timezone(timedelta(hours=-5))
db=SessionLocal()
rating=st.fit_event_rating(db)
times=st.hourly_times(datetime(2017,8,25,tzinfo=timezone.utc),datetime(2017,9,3,5,tzinfo=timezone.utc))
obs=st.observed_stage(db,times,rating)
fim=ie.FimLibrary.load(D+"fim_hgtt2/fim_extents.gpkg"); road=ie.load_road_graph(db,fim)
hg=ie.high_ground_nodes(road,fim,D+"dem_3dep_10m.tif",float(obs.stage_ft.max())*0.3048)
zn=ie.zone_nodes(db,road)
peak_layer=max(fim.layer_for_stage(s) for s in obs.stage_ft)
fl=road.edge_flood_layer
flooded={e for e,l in fl.items() if l<=peak_layer}

# ---------- Q1: fraction flooded, by denominator
from app.models import RoadSegment
segs=gpd.GeoDataFrame([{"e":tuple(int(x) for x in s.graph_edge_id.split('-')),"ex":s.is_bridge or s.is_tunnel,"geometry":to_shape(s.geometry)} for s in db.scalars(select(RoadSegment))],crs=4326).to_crs(32615)
segs["flooded"]=segs.e.isin(flooded)
maxext=fim.extents[-1]; peakext=fim.extents[peak_layer]
reach_box=box(*maxext.bounds)
zones_union=gpd.GeoSeries([to_shape(z.boundary) for z in zn],crs=4326).to_crs(32615).union_all()
print(f"Q1  peak OBS stage {obs.stage_ft.max():.2f} ft -> FIM layer {fim.stages_ft[peak_layer]} ft; peak extent {peakext.area/1e6:.2f} km2")
for name,mask in [("all segments in bbox",np.ones(len(segs),bool)),
                  ("segments in FIM reach bounding box",segs.intersects(reach_box).values),
                  ("segments in the 17 zones",segs.intersects(zones_union).values),
                  ("segments touching the peak flood extent",segs.intersects(peakext).values)]:
    m=segs[mask]; print(f"    {name:42s} {int(m.flooded.sum()):5d} / {len(m):5d} flooded = {m.flooded.mean():6.1%}   (+{int((m.ex & m.intersects(peakext)).sum())} bridges/tunnels exempt)")
# stage->elevation sanity: DEM ground under flooded vs dry segment midpoints, vs WSE
with rasterio.open(D+"dem_3dep_10m.tif") as dem:
    near=segs[segs.intersects(maxext.buffer(300))].copy()
    near["z"]=[v[0] for v in dem.sample([(g.interpolate(0.5,normalized=True).x,g.interpolate(0.5,normalized=True).y) for g in near.geometry])]
wse=float(obs.stage_ft.max())*0.3048
f=near[near.flooded & ~near.ex]; d=near[~near.flooded & ~near.ex]
print(f"    ground elev (3DEP) at segment midpoints within 300 m of floodplain; peak WSE at gauge {wse:.2f} m NAVD88:")
print(f"      flooded: median {f.z.median():.2f} m, {np.mean(f.z<wse+1):.0%} below WSE+1 m | dry: median {d.z.median():.2f} m, {np.mean(d.z<wse):.0%} below WSE")

# ---------- Q2: bbox/zone sizes & last-mile units
zg=gpd.GeoDataFrame({"geoid":[z.census_geoid for z in zn],"n":[len(v) for v in zn.values()]},geometry=[to_shape(z.boundary) for z in zn],crs=4326).to_crs(32615)
print(f"\nQ2  road-graph bbox: {(-95.36+95.50)*96.6:.1f} x {(29.87-29.74)*111:.1f} km; FIM reach bbox: {(maxext.bounds[2]-maxext.bounds[0])/1000:.1f} x {(maxext.bounds[3]-maxext.bounds[1])/1000:.1f} km")
print(f"    block-group zones: area median {zg.area.median()/1e6:.2f} km2 (range {zg.area.min()/1e6:.2f}-{zg.area.max()/1e6:.2f}); road nodes median {int(zg.n.median())}; "
      f"zones straddling the bayou (peak extent splits them): {sum(1 for g in zg.geometry if g.difference(peakext.buffer(1)).geom_type=='MultiPolygon')}")
# census blocks (last-mile units) intersecting the zones
bb=gpd.GeoSeries([zones_union],crs=32615).to_crs(4326).total_bounds
feats=[];off=0
while True:
    r=requests.get("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer/10/query",params=dict(geometry=",".join(map(str,bb)),geometryType="esriGeometryEnvelope",inSR=4326,spatialRel="esriSpatialRelIntersects",outFields="GEOID,POP100",outSR=4326,f="geojson",resultOffset=off,resultRecordCount=1000),timeout=180).json()
    feats+=r["features"]; off+=len(r["features"])
    if not r["features"] or not r.get("properties",{}).get("exceededTransferLimit") and len(r["features"])<1000: break
blocks=gpd.GeoDataFrame.from_features(feats,crs=4326).to_crs(32615)
blocks=blocks[blocks.representative_point().within(zones_union)]
node_ids=list(road.node_xy); pts=gpd.GeoDataFrame({"n":node_ids},geometry=[Point(road.node_xy[n]) for n in node_ids],crs=32615)
j=gpd.sjoin(pts,blocks[["GEOID","POP100","geometry"]],predicate="within")
bnodes=j.groupby("GEOID").n.apply(list).to_dict()
print(f"    2020 census blocks in the zones: {len(blocks)} (median {blocks.area.median()/1e3:.0f}k m2 ~ {np.sqrt(blocks.area.median()):.0f} m side), {len(bnodes)} with road nodes")

# isolation at block level + stranded per hour (reuse engine with blocks as pseudo-zones)
class B:  # minimal stand-in with the attributes run_isolation reads
    def __init__(s,g): s.id=g; s.census_geoid=g
bz={B(g):v for g,v in bnodes.items()}
run=ie.run_isolation(road,fim,obs,bz,hg)
iso=[z for z in run.zones if z.first_isolated_at]
pop=dict(zip(blocks.GEOID,blocks.POP100))
print(f"    OBS run at census-block level: {len(iso)} of {len(run.zones)} blocks fully isolated, population {sum(pop[z.census_geoid] for z in iso):,} (of {int(blocks.POP100.sum()):,})")
for z in sorted(iso,key=lambda z:z.first_isolated_at)[:12]:
    print(f"      block {z.census_geoid} pop {pop[z.census_geoid]:4d} nodes {z.n_nodes:3d} isolated {z.first_isolated_at.astimezone(CDT):%m-%d %H:%M} CDT  reconnected {z.reconnected_at.astimezone(CDT).strftime('%m-%d %H:%M') if z.reconnected_at else 'never in window'}")
if len(iso)>12: print(f"      ... {len(iso)-12} more")
iso_times=sorted(z.first_isolated_at for z in iso)

# ---------- Q3: exact (15-min) signal times, not hourly
h_t,h=st._series(db,st.USGS_SOURCE,"gage_height_ft",measured_only=True)
def cross(th):
    i=np.argmax(h>th) if (h>th).any() else None
    if i is None or i==0: return None
    frac=(th-h[i-1])/(h[i]-h[i-1]); return datetime.fromtimestamp(h_t[i-1]+frac*(h_t[i]-h_t[i-1]),tz=timezone.utc)
first_layer=int(min(l for l in fl.values() if np.isfinite(l)))
# engine uses the smallest layer >= stage, so layer L takes effect once stage > stages[L-1]
thr=lambda L: fim.stages_ft[L-1] if L>0 else -np.inf
cut_hours=[t for t,a,b in zip(run.stage.times,run.stranded_node_count,run.submerged_node_count) if a+b]
first_str_layer=next(l for l,a in zip(run.layer_index,run.stranded_node_count) if a)
events={"gauge > flood stage 32.0 ft":cross(32.0),
        f"first segment floods (stage > {thr(first_layer)} ft, layer {fim.stages_ft[first_layer]})":cross(thr(first_layer)),
        f"first dry node stranded (stage > {thr(first_str_layer)} ft, layer {fim.stages_ft[first_str_layer]})":cross(thr(first_str_layer))}
if iso:
    iso_layer=min(run.layer_index[run.stage.times.index(t)] for t in iso_times[:1])
    events[f"first census block fully isolated (stage > {thr(iso_layer)} ft)"]=cross(thr(iso_layer))
base=events["gauge > flood stage 32.0 ft"]
print("\nQ3  exact crossing times from 15-min measured stage (linear interpolation):")
for k,t in events.items():
    print(f"    {k:62s} {t.astimezone(CDT):%m-%d %H:%M} CDT   vs flood-stage alarm: {(base-t).total_seconds()/60:+6.0f} min   vs start of 8/27 CDT: {(datetime(2017,8,27,tzinfo=CDT)-t).total_seconds()/60:+6.0f} min")

# ---------- Q4: entry-node adjacency
print("\nQ4  zone entry segments (roads crossing a zone boundary) that flood at peak, per block-group zone:")
tot_e=tot_f=0; zones_with=0
for z,nodes in zn.items():
    ns=set(nodes); entry=[(u,v,k) for u in ns for v,kd in road.graph[u].items() if v not in ns for k in kd]
    key=lambda u,v,k: (u,v,k) if (u,v,k) in fl else (v,u,k)
    fe=[e for e in entry if fl.get(key(*e),np.inf)<=peak_layer]
    inner=[(u,v,k) for u in ns for v,kd in road.graph[u].items() if v in ns and u<v for k in kd]
    fi=[e for e in inner if fl.get(key(*e),np.inf)<=peak_layer]
    tot_e+=len(entry); tot_f+=len(fe); zones_with+=bool(fe)
    print(f"    {z.census_geoid}: entry roads {len(entry):3d}, flooded {len(fe):2d} | internal roads {len(inner):3d}, flooded {len(fi):3d}")
print(f"    total: {tot_f}/{tot_e} entry roads flooded ({tot_f/tot_e:.0%}); zones with >=1 flooded entry road: {zones_with}/17")

print("\nQ2b isolated blocks: dry-stranded vs submerged at their worst hour")
dry_blocks=0; dry_pop=0
for z in iso:
    L=run.layer_index[run.stage.times.index(z.first_isolated_at)]
    L=max(run.layer_index[i] for i,f in enumerate(z.reachable_fraction) if f==0)
    g=road.graph.copy(); g.remove_edges_from([e for e,l in fl.items() if l<=L])
    nodes=bnodes[z.census_geoid]; dry=[n for n in nodes if g.degree(n)>0]
    if dry: dry_blocks+=1; dry_pop+=pop[z.census_geoid]
    print(f"    {z.census_geoid} pop {pop[z.census_geoid]:4d}: {len(dry)}/{len(nodes)} nodes dry-but-cut-off, isolated for {(z.reconnected_at-z.first_isolated_at).total_seconds()/3600:.0f} h")
print(f"    blocks isolated with at least one DRY node: {dry_blocks}/{len(iso)}, population {dry_pop}")
