CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/*.parquet', tier='gpu', name='orders', cols=['o_orderkey','o_orderpriority']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/*.parquet', tier='gpu', name='lineitem', cols=['l_orderkey','l_shipmode','l_commitdate','l_receiptdate','l_shipdate']);
.print __PIN_END__
.mode csv
.timer on
.print __ITER__ 1
select
  l.l_shipmode,
  sum(case
    when o.o_orderpriority = '1-URGENT'
      or o.o_orderpriority = '2-HIGH'
      then 1
    else 0
  end) as high_line_count,
  sum(case
    when o.o_orderpriority <> '1-URGENT'
      and o.o_orderpriority <> '2-HIGH'
      then 1
    else 0
  end) as low_line_count
from
  orders o,
  lineitem l
where
  o.o_orderkey = l.l_orderkey
  and l.l_shipmode in ('TRUCK', 'REG AIR')
  and l.l_commitdate < l.l_receiptdate
  and l.l_shipdate < l.l_commitdate
  and l.l_receiptdate >= date '1994-01-01'
  and l.l_receiptdate < date '1995-01-01'
group by
  l.l_shipmode
order by
  l.l_shipmode;
.print __ITER__ 2
select
  l.l_shipmode,
  sum(case
    when o.o_orderpriority = '1-URGENT'
      or o.o_orderpriority = '2-HIGH'
      then 1
    else 0
  end) as high_line_count,
  sum(case
    when o.o_orderpriority <> '1-URGENT'
      and o.o_orderpriority <> '2-HIGH'
      then 1
    else 0
  end) as low_line_count
from
  orders o,
  lineitem l
where
  o.o_orderkey = l.l_orderkey
  and l.l_shipmode in ('TRUCK', 'REG AIR')
  and l.l_commitdate < l.l_receiptdate
  and l.l_shipdate < l.l_commitdate
  and l.l_receiptdate >= date '1994-01-01'
  and l.l_receiptdate < date '1995-01-01'
group by
  l.l_shipmode
order by
  l.l_shipmode;
.print __ITER__ 3
select
  l.l_shipmode,
  sum(case
    when o.o_orderpriority = '1-URGENT'
      or o.o_orderpriority = '2-HIGH'
      then 1
    else 0
  end) as high_line_count,
  sum(case
    when o.o_orderpriority <> '1-URGENT'
      and o.o_orderpriority <> '2-HIGH'
      then 1
    else 0
  end) as low_line_count
from
  orders o,
  lineitem l
where
  o.o_orderkey = l.l_orderkey
  and l.l_shipmode in ('TRUCK', 'REG AIR')
  and l.l_commitdate < l.l_receiptdate
  and l.l_shipdate < l.l_commitdate
  and l.l_receiptdate >= date '1994-01-01'
  and l.l_receiptdate < date '1995-01-01'
group by
  l.l_shipmode
order by
  l.l_shipmode;
.print __ITER__ 4
select
  l.l_shipmode,
  sum(case
    when o.o_orderpriority = '1-URGENT'
      or o.o_orderpriority = '2-HIGH'
      then 1
    else 0
  end) as high_line_count,
  sum(case
    when o.o_orderpriority <> '1-URGENT'
      and o.o_orderpriority <> '2-HIGH'
      then 1
    else 0
  end) as low_line_count
from
  orders o,
  lineitem l
where
  o.o_orderkey = l.l_orderkey
  and l.l_shipmode in ('TRUCK', 'REG AIR')
  and l.l_commitdate < l.l_receiptdate
  and l.l_shipdate < l.l_commitdate
  and l.l_receiptdate >= date '1994-01-01'
  and l.l_receiptdate < date '1995-01-01'
group by
  l.l_shipmode
order by
  l.l_shipmode;
