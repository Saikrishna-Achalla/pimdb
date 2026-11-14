CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
CREATE VIEW customer AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/customer/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
CREATE VIEW nation AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/part.0.parquet']);
CREATE VIEW region AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/region/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/*.parquet', tier='gpu', name='orders', cols=['o_custkey','o_orderkey','o_orderdate']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/*.parquet', tier='gpu', name='lineitem', cols=['l_orderkey','l_suppkey','l_extendedprice','l_discount']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/*.parquet', tier='gpu', name='supplier', cols=['s_suppkey','s_nationkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/*.parquet', tier='gpu', name='nation', cols=['n_nationkey','n_name','n_regionkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/region/*.parquet', tier='gpu', name='region', cols=['r_regionkey','r_name']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/customer/*.parquet', tier='gpu', name='customer', cols=['c_custkey','c_nationkey']);
.print __PIN_END__
.mode csv
.timer on
.print __ITER__ 1
select
  n.n_name,
  sum(l.l_extendedprice * (1 - l.l_discount)) as revenue
from
  orders o,
  lineitem l,
  supplier s,
  nation n,
  region r,
  customer c
where
  c.c_custkey = o.o_custkey
  and l.l_orderkey = o.o_orderkey
  and l.l_suppkey = s.s_suppkey
  and c.c_nationkey = s.s_nationkey
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and o.o_orderdate >= date '1997-01-01'
  and o.o_orderdate < date '1998-01-01'
group by
  n.n_name
order by
  revenue desc;
.print __ITER__ 2
select
  n.n_name,
  sum(l.l_extendedprice * (1 - l.l_discount)) as revenue
from
  orders o,
  lineitem l,
  supplier s,
  nation n,
  region r,
  customer c
where
  c.c_custkey = o.o_custkey
  and l.l_orderkey = o.o_orderkey
  and l.l_suppkey = s.s_suppkey
  and c.c_nationkey = s.s_nationkey
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and o.o_orderdate >= date '1997-01-01'
  and o.o_orderdate < date '1998-01-01'
group by
  n.n_name
order by
  revenue desc;
.print __ITER__ 3
select
  n.n_name,
  sum(l.l_extendedprice * (1 - l.l_discount)) as revenue
from
  orders o,
  lineitem l,
  supplier s,
  nation n,
  region r,
  customer c
where
  c.c_custkey = o.o_custkey
  and l.l_orderkey = o.o_orderkey
  and l.l_suppkey = s.s_suppkey
  and c.c_nationkey = s.s_nationkey
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and o.o_orderdate >= date '1997-01-01'
  and o.o_orderdate < date '1998-01-01'
group by
  n.n_name
order by
  revenue desc;
.print __ITER__ 4
select
  n.n_name,
  sum(l.l_extendedprice * (1 - l.l_discount)) as revenue
from
  orders o,
  lineitem l,
  supplier s,
  nation n,
  region r,
  customer c
where
  c.c_custkey = o.o_custkey
  and l.l_orderkey = o.o_orderkey
  and l.l_suppkey = s.s_suppkey
  and c.c_nationkey = s.s_nationkey
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and o.o_orderdate >= date '1997-01-01'
  and o.o_orderdate < date '1998-01-01'
group by
  n.n_name
order by
  revenue desc;
.print __ITER__ 5
select
  n.n_name,
  sum(l.l_extendedprice * (1 - l.l_discount)) as revenue
from
  orders o,
  lineitem l,
  supplier s,
  nation n,
  region r,
  customer c
where
  c.c_custkey = o.o_custkey
  and l.l_orderkey = o.o_orderkey
  and l.l_suppkey = s.s_suppkey
  and c.c_nationkey = s.s_nationkey
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and o.o_orderdate >= date '1997-01-01'
  and o.o_orderdate < date '1998-01-01'
group by
  n.n_name
order by
  revenue desc;
