CREATE VIEW part AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/part/part.0.parquet']);
CREATE VIEW partsupp AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/partsupp/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
CREATE VIEW nation AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/part.0.parquet']);
CREATE VIEW region AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/region/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/part/*.parquet', tier='gpu', name='part', cols=['p_partkey','p_mfgr','p_size','p_type']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/*.parquet', tier='gpu', name='supplier', cols=['s_suppkey','s_acctbal','s_name','s_address','s_phone','s_comment','s_nationkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/*.parquet', tier='gpu', name='nation', cols=['n_nationkey','n_name','n_regionkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/region/*.parquet', tier='gpu', name='region', cols=['r_regionkey','r_name']);
.print __PIN_END__
.mode csv
.timer on
.shell sleep 0.3
.print __ITER__ 1
select
  s.s_acctbal,
  s.s_name,
  n.n_name,
  p.p_partkey,
  p.p_mfgr,
  s.s_address,
  s.s_phone,
  s.s_comment
from
  part p,
  supplier s,
  partsupp ps,
  nation n,
  region r
where
  p.p_partkey = ps.ps_partkey
  and s.s_suppkey = ps.ps_suppkey
  and p.p_size = 41
  and p.p_type like '%NICKEL'
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and ps.ps_supplycost = (
    select
      min(ps.ps_supplycost)
    from
      partsupp ps,
      supplier s,
      nation n,
      region r
    where
      p.p_partkey = ps.ps_partkey
      and s.s_suppkey = ps.ps_suppkey
      and s.s_nationkey = n.n_nationkey
      and n.n_regionkey = r.r_regionkey
      and r.r_name = 'EUROPE'
  )
order by
  s.s_acctbal desc,
  n.n_name,
  s.s_name,
  p.p_partkey
limit 100;
.shell sleep 0.3
.print __ITER__ 2
select
  s.s_acctbal,
  s.s_name,
  n.n_name,
  p.p_partkey,
  p.p_mfgr,
  s.s_address,
  s.s_phone,
  s.s_comment
from
  part p,
  supplier s,
  partsupp ps,
  nation n,
  region r
where
  p.p_partkey = ps.ps_partkey
  and s.s_suppkey = ps.ps_suppkey
  and p.p_size = 41
  and p.p_type like '%NICKEL'
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and ps.ps_supplycost = (
    select
      min(ps.ps_supplycost)
    from
      partsupp ps,
      supplier s,
      nation n,
      region r
    where
      p.p_partkey = ps.ps_partkey
      and s.s_suppkey = ps.ps_suppkey
      and s.s_nationkey = n.n_nationkey
      and n.n_regionkey = r.r_regionkey
      and r.r_name = 'EUROPE'
  )
order by
  s.s_acctbal desc,
  n.n_name,
  s.s_name,
  p.p_partkey
limit 100;
.shell sleep 0.3
.print __ITER__ 3
select
  s.s_acctbal,
  s.s_name,
  n.n_name,
  p.p_partkey,
  p.p_mfgr,
  s.s_address,
  s.s_phone,
  s.s_comment
from
  part p,
  supplier s,
  partsupp ps,
  nation n,
  region r
where
  p.p_partkey = ps.ps_partkey
  and s.s_suppkey = ps.ps_suppkey
  and p.p_size = 41
  and p.p_type like '%NICKEL'
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and ps.ps_supplycost = (
    select
      min(ps.ps_supplycost)
    from
      partsupp ps,
      supplier s,
      nation n,
      region r
    where
      p.p_partkey = ps.ps_partkey
      and s.s_suppkey = ps.ps_suppkey
      and s.s_nationkey = n.n_nationkey
      and n.n_regionkey = r.r_regionkey
      and r.r_name = 'EUROPE'
  )
order by
  s.s_acctbal desc,
  n.n_name,
  s.s_name,
  p.p_partkey
limit 100;
.shell sleep 0.3
.print __ITER__ 4
select
  s.s_acctbal,
  s.s_name,
  n.n_name,
  p.p_partkey,
  p.p_mfgr,
  s.s_address,
  s.s_phone,
  s.s_comment
from
  part p,
  supplier s,
  partsupp ps,
  nation n,
  region r
where
  p.p_partkey = ps.ps_partkey
  and s.s_suppkey = ps.ps_suppkey
  and p.p_size = 41
  and p.p_type like '%NICKEL'
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and ps.ps_supplycost = (
    select
      min(ps.ps_supplycost)
    from
      partsupp ps,
      supplier s,
      nation n,
      region r
    where
      p.p_partkey = ps.ps_partkey
      and s.s_suppkey = ps.ps_suppkey
      and s.s_nationkey = n.n_nationkey
      and n.n_regionkey = r.r_regionkey
      and r.r_name = 'EUROPE'
  )
order by
  s.s_acctbal desc,
  n.n_name,
  s.s_name,
  p.p_partkey
limit 100;
.shell sleep 0.3
.print __ITER__ 5
select
  s.s_acctbal,
  s.s_name,
  n.n_name,
  p.p_partkey,
  p.p_mfgr,
  s.s_address,
  s.s_phone,
  s.s_comment
from
  part p,
  supplier s,
  partsupp ps,
  nation n,
  region r
where
  p.p_partkey = ps.ps_partkey
  and s.s_suppkey = ps.ps_suppkey
  and p.p_size = 41
  and p.p_type like '%NICKEL'
  and s.s_nationkey = n.n_nationkey
  and n.n_regionkey = r.r_regionkey
  and r.r_name = 'EUROPE'
  and ps.ps_supplycost = (
    select
      min(ps.ps_supplycost)
    from
      partsupp ps,
      supplier s,
      nation n,
      region r
    where
      p.p_partkey = ps.ps_partkey
      and s.s_suppkey = ps.ps_suppkey
      and s.s_nationkey = n.n_nationkey
      and n.n_regionkey = r.r_regionkey
      and r.r_name = 'EUROPE'
  )
order by
  s.s_acctbal desc,
  n.n_name,
  s.s_name,
  p.p_partkey
limit 100;
