CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
CREATE VIEW part AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/part/part.0.parquet']);
CREATE VIEW partsupp AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/partsupp/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
CREATE VIEW nation AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/part/*.parquet', tier='gpu', name='part', cols=['p_partkey','p_name']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/*.parquet', tier='gpu', name='supplier', cols=['s_suppkey','s_nationkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/*.parquet', tier='gpu', name='lineitem', cols=['l_suppkey','l_partkey','l_orderkey','l_extendedprice','l_discount','l_quantity']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/partsupp/*.parquet', tier='gpu', name='partsupp', cols=['ps_suppkey','ps_partkey','ps_supplycost']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/*.parquet', tier='gpu', name='orders', cols=['o_orderkey','o_orderdate']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/*.parquet', tier='gpu', name='nation', cols=['n_nationkey','n_name']);
.print __PIN_END__
.mode csv
.timer on
.print __ITER__ 1
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 2
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 3
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 4
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 5
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 6
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 7
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 8
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 9
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 10
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 11
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 12
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 13
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 14
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
.print __ITER__ 15
select
  nation,
  o_year,
  sum(amount) as sum_profit
from
  (
    select
      n.n_name as nation,
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) - ps.ps_supplycost * l.l_quantity as amount
    from
      part p,
      supplier s,
      lineitem l,
      partsupp ps,
      orders o,
      nation n
    where
      s.s_suppkey = l.l_suppkey
      and ps.ps_suppkey = l.l_suppkey
      and ps.ps_partkey = l.l_partkey
      and p.p_partkey = l.l_partkey
      and o.o_orderkey = l.l_orderkey
      and s.s_nationkey = n.n_nationkey
      and p.p_name like '%yellow%'
  ) as profit
group by
  nation,
  o_year
order by
  nation,
  o_year desc;
