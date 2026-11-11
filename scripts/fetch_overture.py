"""Fetch Overture Maps buildings for a bbox via DuckDB (public S3, no credentials)."""
import sys, duckdb
RELEASE = "2026-10-21.0"
W,S,E,N = [float(x) for x in sys.argv[1:5]]
out = sys.argv[5]
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
con.execute(f"""
COPY (
 SELECT id, ST_AsText(geometry) AS wkt, height, num_floors, subtype, class, names.primary AS name,
        sources[1].dataset AS src_dataset, sources[1].record_id AS src_id, has_parts
 FROM read_parquet('s3://overturemaps-us-west-2/release/{RELEASE}/theme=buildings/type=building/*', hive_partitioning=1)
 WHERE bbox.xmin BETWEEN {W} AND {E} AND bbox.ymin BETWEEN {S} AND {N}
) TO '{out}' (FORMAT PARQUET);
""")
print(con.execute(f"select count(*), count(height), count(num_floors) from read_parquet('{out}')").fetchall())
print(con.execute(f"select src_dataset,count(*) from read_parquet('{out}') group by 1").fetchall())
