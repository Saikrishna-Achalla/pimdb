CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
CREATE VIEW customer AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/customer/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
CREATE VIEW nation AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/*.parquet', tier='gpu', name='supplier', cols=['s_suppkey','s_nationkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/*.parquet', tier='gpu', name='lineitem', cols=['l_suppkey','l_orderkey','l_shipdate','l_extendedprice','l_discount']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/*.parquet', tier='gpu', name='orders', cols=['o_orderkey','o_custkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/customer/*.parquet', tier='gpu', name='customer', cols=['c_custkey','c_nationkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/*.parquet', tier='gpu', name='nation', cols=['n_nationkey','n_name']);
.print __PIN_END__
.mode csv
.timer on
.print __ITER__ 1
select
  supp_nation,
  cust_nation,
  l_year,
  sum(volume) as revenue
from
  (
    select
      n1.n_name as supp_nation,
      n2.n_name as cust_nation,
      extract(year from l.l_shipdate) as l_year,
      l.l_extendedprice * (1 - l.l_discount) as volume
    from
      supplier s,
      lineitem l,
      orders o,
      customer c,
      nation n1,
      nation n2
    where
      s.s_suppkey = l.l_suppkey
      and o.o_orderkey = l.l_orderkey
      and c.c_custkey = o.o_custkey
      and s.s_nationkey = n1.n_nationkey
      and c.c_nationkey = n2.n_nationkey
      and (
        (n1.n_name = 'EGYPT' and n2.n_name = 'UNITED STATES')
        or (n1.n_name = 'UNITED STATES' and n2.n_name = 'EGYPT')
      )
      and l.l_shipdate between date '1995-01-01' and date '1996-12-31'
  ) as shipping
group by
  supp_nation,
  cust_nation,
  l_year
order by
  supp_nation,
  cust_nation,
  l_year;
.print __ITER__ 2
select
  supp_nation,
  cust_nation,
  l_year,
  sum(volume) as revenue
from
  (
    select
      n1.n_name as supp_nation,
      n2.n_name as cust_nation,
      extract(year from l.l_shipdate) as l_year,
      l.l_extendedprice * (1 - l.l_discount) as volume
    from
      supplier s,
      lineitem l,
      orders o,
      customer c,
      nation n1,
      nation n2
    where
      s.s_suppkey = l.l_suppkey
      and o.o_orderkey = l.l_orderkey
      and c.c_custkey = o.o_custkey
      and s.s_nationkey = n1.n_nationkey
      and c.c_nationkey = n2.n_nationkey
      and (
        (n1.n_name = 'EGYPT' and n2.n_name = 'UNITED STATES')
        or (n1.n_name = 'UNITED STATES' and n2.n_name = 'EGYPT')
      )
      and l.l_shipdate between date '1995-01-01' and date '1996-12-31'
  ) as shipping
group by
  supp_nation,
  cust_nation,
  l_year
order by
  supp_nation,
  cust_nation,
  l_year;
.print __ITER__ 3
select
  supp_nation,
  cust_nation,
  l_year,
  sum(volume) as revenue
from
  (
    select
      n1.n_name as supp_nation,
      n2.n_name as cust_nation,
      extract(year from l.l_shipdate) as l_year,
      l.l_extendedprice * (1 - l.l_discount) as volume
    from
      supplier s,
      lineitem l,
      orders o,
      customer c,
      nation n1,
      nation n2
    where
      s.s_suppkey = l.l_suppkey
      and o.o_orderkey = l.l_orderkey
      and c.c_custkey = o.o_custkey
      and s.s_nationkey = n1.n_nationkey
      and c.c_nationkey = n2.n_nationkey
      and (
        (n1.n_name = 'EGYPT' and n2.n_name = 'UNITED STATES')
        or (n1.n_name = 'UNITED STATES' and n2.n_name = 'EGYPT')
      )
      and l.l_shipdate between date '1995-01-01' and date '1996-12-31'
  ) as shipping
group by
  supp_nation,
  cust_nation,
  l_year
order by
  supp_nation,
  cust_nation,
  l_year;
.print __ITER__ 4
select
  supp_nation,
  cust_nation,
  l_year,
  sum(volume) as revenue
from
  (
    select
      n1.n_name as supp_nation,
      n2.n_name as cust_nation,
      extract(year from l.l_shipdate) as l_year,
      l.l_extendedprice * (1 - l.l_discount) as volume
    from
      supplier s,
      lineitem l,
      orders o,
      customer c,
      nation n1,
      nation n2
    where
      s.s_suppkey = l.l_suppkey
      and o.o_orderkey = l.l_orderkey
      and c.c_custkey = o.o_custkey
      and s.s_nationkey = n1.n_nationkey
      and c.c_nationkey = n2.n_nationkey
      and (
        (n1.n_name = 'EGYPT' and n2.n_name = 'UNITED STATES')
        or (n1.n_name = 'UNITED STATES' and n2.n_name = 'EGYPT')
      )
      and l.l_shipdate between date '1995-01-01' and date '1996-12-31'
  ) as shipping
group by
  supp_nation,
  cust_nation,
  l_year
order by
  supp_nation,
  cust_nation,
  l_year;
.print __ITER__ 5
select
  supp_nation,
  cust_nation,
  l_year,
  sum(volume) as revenue
from
  (
    select
      n1.n_name as supp_nation,
      n2.n_name as cust_nation,
      extract(year from l.l_shipdate) as l_year,
      l.l_extendedprice * (1 - l.l_discount) as volume
    from
      supplier s,
      lineitem l,
      orders o,
      customer c,
      nation n1,
      nation n2
    where
      s.s_suppkey = l.l_suppkey
      and o.o_orderkey = l.l_orderkey
      and c.c_custkey = o.o_custkey
      and s.s_nationkey = n1.n_nationkey
      and c.c_nationkey = n2.n_nationkey
      and (
        (n1.n_name = 'EGYPT' and n2.n_name = 'UNITED STATES')
        or (n1.n_name = 'UNITED STATES' and n2.n_name = 'EGYPT')
      )
      and l.l_shipdate between date '1995-01-01' and date '1996-12-31'
  ) as shipping
group by
  supp_nation,
  cust_nation,
  l_year
order by
  supp_nation,
  cust_nation,
  l_year;
