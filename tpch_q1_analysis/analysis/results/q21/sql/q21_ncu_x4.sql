CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
CREATE VIEW nation AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/*.parquet', tier='gpu', name='supplier', cols=['s_suppkey','s_nationkey','s_name']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/*.parquet', tier='gpu', name='lineitem', cols=['l_suppkey','l_orderkey','l_receiptdate','l_commitdate']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/*.parquet', tier='gpu', name='orders', cols=['o_orderkey','o_orderstatus']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/*.parquet', tier='gpu', name='nation', cols=['n_nationkey','n_name']);
.print __PIN_END__
.mode csv
.timer on
.print __ITER__ 1
select
  s.s_name,
  count(*) as numwait
from
  supplier s,
  lineitem l1,
  orders o,
  nation n
where
  s.s_suppkey = l1.l_suppkey
  and o.o_orderkey = l1.l_orderkey
  and o.o_orderstatus = 'F'
  and l1.l_receiptdate > l1.l_commitdate
  and exists (
    select
      *
    from
      lineitem l2
    where
      l2.l_orderkey = l1.l_orderkey
      and l2.l_suppkey <> l1.l_suppkey
  )
  and not exists (
    select
      *
    from
      lineitem l3
    where
      l3.l_orderkey = l1.l_orderkey
      and l3.l_suppkey <> l1.l_suppkey
      and l3.l_receiptdate > l3.l_commitdate
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'BRAZIL'
group by
  s.s_name
order by
  numwait desc,
  s.s_name
limit 100;
.print __ITER__ 2
select
  s.s_name,
  count(*) as numwait
from
  supplier s,
  lineitem l1,
  orders o,
  nation n
where
  s.s_suppkey = l1.l_suppkey
  and o.o_orderkey = l1.l_orderkey
  and o.o_orderstatus = 'F'
  and l1.l_receiptdate > l1.l_commitdate
  and exists (
    select
      *
    from
      lineitem l2
    where
      l2.l_orderkey = l1.l_orderkey
      and l2.l_suppkey <> l1.l_suppkey
  )
  and not exists (
    select
      *
    from
      lineitem l3
    where
      l3.l_orderkey = l1.l_orderkey
      and l3.l_suppkey <> l1.l_suppkey
      and l3.l_receiptdate > l3.l_commitdate
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'BRAZIL'
group by
  s.s_name
order by
  numwait desc,
  s.s_name
limit 100;
.print __ITER__ 3
select
  s.s_name,
  count(*) as numwait
from
  supplier s,
  lineitem l1,
  orders o,
  nation n
where
  s.s_suppkey = l1.l_suppkey
  and o.o_orderkey = l1.l_orderkey
  and o.o_orderstatus = 'F'
  and l1.l_receiptdate > l1.l_commitdate
  and exists (
    select
      *
    from
      lineitem l2
    where
      l2.l_orderkey = l1.l_orderkey
      and l2.l_suppkey <> l1.l_suppkey
  )
  and not exists (
    select
      *
    from
      lineitem l3
    where
      l3.l_orderkey = l1.l_orderkey
      and l3.l_suppkey <> l1.l_suppkey
      and l3.l_receiptdate > l3.l_commitdate
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'BRAZIL'
group by
  s.s_name
order by
  numwait desc,
  s.s_name
limit 100;
.print __ITER__ 4
select
  s.s_name,
  count(*) as numwait
from
  supplier s,
  lineitem l1,
  orders o,
  nation n
where
  s.s_suppkey = l1.l_suppkey
  and o.o_orderkey = l1.l_orderkey
  and o.o_orderstatus = 'F'
  and l1.l_receiptdate > l1.l_commitdate
  and exists (
    select
      *
    from
      lineitem l2
    where
      l2.l_orderkey = l1.l_orderkey
      and l2.l_suppkey <> l1.l_suppkey
  )
  and not exists (
    select
      *
    from
      lineitem l3
    where
      l3.l_orderkey = l1.l_orderkey
      and l3.l_suppkey <> l1.l_suppkey
      and l3.l_receiptdate > l3.l_commitdate
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'BRAZIL'
group by
  s.s_name
order by
  numwait desc,
  s.s_name
limit 100;
