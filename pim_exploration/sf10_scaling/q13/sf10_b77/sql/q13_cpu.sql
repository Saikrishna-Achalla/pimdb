CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf10/orders/part.0.parquet']);
CREATE VIEW customer AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf10/customer/part.0.parquet']);
.mode csv
.timer on
.print __ITER__ 1
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 2
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 3
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 4
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 5
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 6
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 7
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 8
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 9
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 10
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 11
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 12
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 13
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 14
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
.print __ITER__ 15
select
  c_count,
  count(*) as custdist
from
  (
    select
      c.c_custkey,
      count(o.o_orderkey)
    from
      customer c
      left outer join orders o
        on c.c_custkey = o.o_custkey
        and o.o_comment not like '%special%requests%'
    group by
      c.c_custkey
  ) as orders (c_custkey, c_count)
group by
  c_count
order by
  custdist desc,
  c_count desc;
