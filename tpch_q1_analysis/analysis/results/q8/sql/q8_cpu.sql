CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
CREATE VIEW customer AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/customer/part.0.parquet']);
CREATE VIEW part AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/part/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
CREATE VIEW nation AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/part.0.parquet']);
CREATE VIEW region AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/region/part.0.parquet']);
.mode csv
.timer on
.print __ITER__ 1
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 2
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 3
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 4
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 5
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 6
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 7
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 8
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 9
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 10
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 11
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 12
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 13
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 14
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
.print __ITER__ 15
select
  o_year,
  sum(case
    when nation = 'EGYPT' then volume
    else 0
  end) / sum(volume) as mkt_share
from
  (
    select
      extract(year from o.o_orderdate) as o_year,
      l.l_extendedprice * (1 - l.l_discount) as volume,
      n2.n_name as nation
    from
      lineitem l,
      part p,
      supplier s,
      orders o,
      customer c,
      nation n1,
      nation n2,
      region r
    where
      p.p_partkey = l.l_partkey
      and s.s_suppkey = l.l_suppkey
      and l.l_orderkey = o.o_orderkey
      and o.o_custkey = c.c_custkey
      and c.c_nationkey = n1.n_nationkey
      and n1.n_regionkey = r.r_regionkey
      and r.r_name = 'MIDDLE EAST'
      and s.s_nationkey = n2.n_nationkey
      and o.o_orderdate between date '1995-01-01' and date '1996-12-31'
      and p.p_type = 'PROMO BRUSHED COPPER'
  ) as all_nations
group by
  o_year
order by
  o_year;
