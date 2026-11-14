CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW part AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/part/part.0.parquet']);
CREATE VIEW partsupp AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/partsupp/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
CREATE VIEW nation AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/part.0.parquet']);
.mode csv
.timer on
.print __ITER__ 1
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 2
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 3
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 4
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 5
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 6
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 7
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 8
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 9
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 10
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 11
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 12
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 13
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 14
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
.print __ITER__ 15
select
  s.s_name,
  s.s_address
from
  supplier s,
  nation n
where
  s.s_suppkey in (
    select
      ps.ps_suppkey
    from
      partsupp ps
    where
      ps. ps_partkey in (
        select
          p.p_partkey
        from
          part p
        where
          p.p_name like 'antique%'
      )
      and ps.ps_availqty > (
        select
          0.5 * sum(l.l_quantity)
        from
          lineitem l
        where
          l.l_partkey = ps.ps_partkey
          and l.l_suppkey = ps.ps_suppkey
          and l.l_shipdate >= date '1993-01-01'
          and l.l_shipdate < date '1994-01-01'
      )
  )
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'KENYA'
order by
  s.s_name;
