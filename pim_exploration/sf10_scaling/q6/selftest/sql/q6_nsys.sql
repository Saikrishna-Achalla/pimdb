CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf10/lineitem/part.0.parquet']);
.print __PIN_BEGIN__

.print __PIN_END__
.mode csv
.timer on
.shell sleep 0.3
.print __ITER__ 1
select
  sum(l_extendedprice * l_discount) as revenue
from
  lineitem
where
  l_shipdate >= date '1997-01-01'
  and l_shipdate < date '1998-01-01'
  and l_discount between 0.03 - 0.01 and 0.03 + 0.01
  and l_quantity < 24;
.shell sleep 0.3
.print __ITER__ 2
select
  sum(l_extendedprice * l_discount) as revenue
from
  lineitem
where
  l_shipdate >= date '1997-01-01'
  and l_shipdate < date '1998-01-01'
  and l_discount between 0.03 - 0.01 and 0.03 + 0.01
  and l_quantity < 24;
.shell sleep 0.3
.print __ITER__ 3
select
  sum(l_extendedprice * l_discount) as revenue
from
  lineitem
where
  l_shipdate >= date '1997-01-01'
  and l_shipdate < date '1998-01-01'
  and l_discount between 0.03 - 0.01 and 0.03 + 0.01
  and l_quantity < 24;
.shell sleep 0.3
.print __ITER__ 4
select
  sum(l_extendedprice * l_discount) as revenue
from
  lineitem
where
  l_shipdate >= date '1997-01-01'
  and l_shipdate < date '1998-01-01'
  and l_discount between 0.03 - 0.01 and 0.03 + 0.01
  and l_quantity < 24;
.shell sleep 0.3
.print __ITER__ 5
select
  sum(l_extendedprice * l_discount) as revenue
from
  lineitem
where
  l_shipdate >= date '1997-01-01'
  and l_shipdate < date '1998-01-01'
  and l_discount between 0.03 - 0.01 and 0.03 + 0.01
  and l_quantity < 24;
