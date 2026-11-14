CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW part AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/part/part.0.parquet']);
.mode csv
.timer on
.print __ITER__ 1
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 2
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 3
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 4
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 5
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 6
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 7
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 8
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 9
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 10
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 11
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 12
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 13
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 14
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
.print __ITER__ 15
select
  sum(l.l_extendedprice) / 7.0 as avg_yearly
from
  lineitem l,
  part p
where
  p.p_partkey = l.l_partkey
  and p.p_brand = 'Brand#13'
  and p.p_container = 'JUMBO CAN'
  and l.l_quantity < (
    select
      0.2 * avg(l2.l_quantity)
    from
      lineitem l2
    where
      l2.l_partkey = p.p_partkey
  );
