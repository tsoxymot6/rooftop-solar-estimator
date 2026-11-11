"""Window-read Open Buildings 2.5D Temporal (2023-06-30) building_height band for the pilot bbox.
Uses ranged HTTPS reads (fsspec + tifffile); writes a small local GeoTIFF (UTM 43N, 0.5 m grid, native ~4 m)."""
import sys, numpy as np, fsspec, tifffile, zarr, pyproj, rasterio
from rasterio.transform import Affine
URL = "https://storage.googleapis.com/open-buildings-temporal-data/v1/geotiffs/3bae4_2023_06_30/tile_hXqKtZuLh78.tif"
X0, Y0, RES = 774780.0, 1444900.0, 0.5
W,S,E,N = [float(x) for x in sys.argv[1:5]]; out = sys.argv[5]
t = pyproj.Transformer.from_crs(4326, 32643, always_xy=True)
x0,y0 = t.transform(W,S); x1,y1 = t.transform(E,N); pad = 60
c0,c1 = int((x0-pad-X0)/RES), int((x1+pad-X0)/RES); r0,r1 = int((Y0-(y1+pad))/RES), int((Y0-(y0-pad))/RES)
fs = fsspec.filesystem("https", block_size=8*1024*1024)
with fs.open(URL) as fh:
    tf = tifffile.TiffFile(fh)
    z = zarr.open(tf.aszarr(level=0), mode="r")
    arr = np.asarray(z[:, r0:r1, c0:c1])
tr = Affine(RES,0,X0+c0*RES, 0,-RES,Y0-r0*RES)
with rasterio.open(out,"w",driver="GTiff",height=arr.shape[1],width=arr.shape[2],count=3,dtype="float32",
                   crs="EPSG:32643",transform=tr,compress="deflate",nodata=-99.0) as o:
    o.write(arr.astype("float32")); o.descriptions=("building_fractional_count","building_height","building_presence")
h = arr[1]; v = h[h>0]
print("shape",arr.shape,"valid>0:",v.size,"pct50/90/max:",np.percentile(v,[50,90,100]).round(1) if v.size else None, "nodata frac",(h==-99).mean().round(3))
