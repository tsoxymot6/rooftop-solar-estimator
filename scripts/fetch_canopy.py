"""Window-read Meta/WRI Global Canopy Height Map (v1, 1 m, CC-BY 4.0) from the public AWS Open Data bucket."""
import sys, numpy as np, fsspec, tifffile, zarr, pyproj, rasterio
from rasterio.transform import Affine
QK = "123303312"
URL = f"https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/{QK}.tif"
W,S,E,N = [float(x) for x in sys.argv[1:5]]; out = sys.argv[5]
fs = fsspec.filesystem("https", block_size=8*1024*1024)
with fs.open(URL) as fh:
    tf = tifffile.TiffFile(fh); p = tf.pages[0]
    print("shape",p.shape,p.dtype,"tiled",p.is_tiled)
    tags = {t.name:t.value for t in p.tags.values()}
    sx,sy,_ = tags["ModelPixelScaleTag"]; tp = tags["ModelTiepointTag"]; ox,oy = tp[3],tp[4]
    gk = tags["GeoKeyDirectoryTag"]; print("geokeys",gk[:24], "origin",ox,oy,"res",sx,sy)
    epsg = 3857 if 3857 in gk else 4326
    pad = 0.0004
    t = pyproj.Transformer.from_crs(4326, epsg, always_xy=True)
    xa,ya = t.transform(W-pad,S-pad); xb,yb = t.transform(E+pad,N+pad)
    c0,c1 = int((xa-ox)/sx), int((xb-ox)/sx); r0,r1 = int((oy-yb)/sy), int((oy-ya)/sy)
    z = zarr.open(tf.aszarr(level=0), mode="r")
    arr = np.asarray(z[r0:r1, c0:c1] if p.ndim==2 else z[0, r0:r1, c0:c1])
tr = Affine(sx,0,ox+c0*sx, 0,-sy,oy-r0*sy)
with rasterio.open(out,"w",driver="GTiff",height=arr.shape[0],width=arr.shape[1],count=1,dtype=str(arr.dtype),
                   crs=f"EPSG:{epsg}",transform=tr,compress="deflate") as o: o.write(arr,1)
v=arr[arr>0]; print("epsg",epsg,"window",arr.shape,"px>0",v.size,"p50/p90/max",np.percentile(v,[50,90,100]).round(1) if v.size else None, "vals>=2m frac",(arr>=2).mean().round(3))
