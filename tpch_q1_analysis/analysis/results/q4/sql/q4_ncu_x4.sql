CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/*.parquet', tier='gpu', name='orders', cols=['o_orderkey','o_orderdate','o_orderpriority']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/*.parquet', tier='gpu', name='lineitem', cols=['l_orderkey','l_commitdate','l_receiptdate']);
.print __PIN_END__
.mode csv
.timer on
.print __ITER__ 1
select
  o.o_orderpriority,
  count(*) as order_count
from
  orders o
where
  o.o_orderdate >= date '1996-10-01'
  and o.o_orderdate < date '1997-01-01'
  and
  exists (
    select
      *
    from
      lineitem l
    where
      l.l_orderkey = o.o_orderkey
      and l.l_commitdate < l.l_receiptdate
  )
group by
  o.o_orderpriority
order by
  o.o_orderpriority;
.print __ITER__ 2
select
  o.o_orderpriority,
  count(*) as order_count
from
  orders o
where
  o.o_orderdate >= date '1996-10-01'
  and o.o_orderdate < date '1997-01-01'
  and
  exists (
    select
      *
    from
      lineitem l
    where
      l.l_orderkey = o.o_orderkey
      and l.l_commitdate < l.l_receiptdate
  )
group by
  o.o_orderpriority
order by
  o.o_orderpriority;
.print __ITER__ 3
select
  o.o_orderpriority,
  count(*) as order_count
from
  orders o
where
  o.o_orderdate >= date '1996-10-01'
  and o.o_orderdate < date '1997-01-01'
  and
  exists (
    select
      *
    from
      lineitem l
    where
      l.l_orderkey = o.o_orderkey
      and l.l_commitdate < l.l_receiptdate
  )
group by
  o.o_orderpriority
order by
  o.o_orderpriority;
.print __ITER__ 4
select
  o.o_orderpriority,
  count(*) as order_count
from
  orders o
where
  o.o_orderdate >= date '1996-10-01'
  and o.o_orderdate < date '1997-01-01'
  and
  exists (
    select
      *
    from
      lineitem l
    where
      l.l_orderkey = o.o_orderkey
      and l.l_commitdate < l.l_receiptdate
  )
group by
  o.o_orderpriority
order by
  o.o_orderpriority;
