CREATE VIEW partsupp AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/partsupp/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
CREATE VIEW nation AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/*.parquet', tier='gpu', name='supplier', cols=['s_suppkey','s_nationkey']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/nation/*.parquet', tier='gpu', name='nation', cols=['n_nationkey','n_name']);
.print __PIN_END__
.mode csv
.timer on
.shell sleep 0.3
.print __ITER__ 1
select
  ps.ps_partkey,
  sum(ps.ps_supplycost * ps.ps_availqty) as value
from
  partsupp ps,
  supplier s,
  nation n
where
  ps.ps_suppkey = s.s_suppkey
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'GERMANY'
group by
  ps.ps_partkey having
    sum(ps.ps_supplycost * ps.ps_availqty) > (
      select
        sum(ps.ps_supplycost * ps.ps_availqty) * 0.00001
      from
        partsupp ps,
        supplier s,
        nation n
      where
        ps.ps_suppkey = s.s_suppkey
        and s.s_nationkey = n.n_nationkey
        and n.n_name = 'GERMANY'
    )
order by
  value desc;
.shell sleep 0.3
.print __ITER__ 2
select
  ps.ps_partkey,
  sum(ps.ps_supplycost * ps.ps_availqty) as value
from
  partsupp ps,
  supplier s,
  nation n
where
  ps.ps_suppkey = s.s_suppkey
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'GERMANY'
group by
  ps.ps_partkey having
    sum(ps.ps_supplycost * ps.ps_availqty) > (
      select
        sum(ps.ps_supplycost * ps.ps_availqty) * 0.00001
      from
        partsupp ps,
        supplier s,
        nation n
      where
        ps.ps_suppkey = s.s_suppkey
        and s.s_nationkey = n.n_nationkey
        and n.n_name = 'GERMANY'
    )
order by
  value desc;
.shell sleep 0.3
.print __ITER__ 3
select
  ps.ps_partkey,
  sum(ps.ps_supplycost * ps.ps_availqty) as value
from
  partsupp ps,
  supplier s,
  nation n
where
  ps.ps_suppkey = s.s_suppkey
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'GERMANY'
group by
  ps.ps_partkey having
    sum(ps.ps_supplycost * ps.ps_availqty) > (
      select
        sum(ps.ps_supplycost * ps.ps_availqty) * 0.00001
      from
        partsupp ps,
        supplier s,
        nation n
      where
        ps.ps_suppkey = s.s_suppkey
        and s.s_nationkey = n.n_nationkey
        and n.n_name = 'GERMANY'
    )
order by
  value desc;
.shell sleep 0.3
.print __ITER__ 4
select
  ps.ps_partkey,
  sum(ps.ps_supplycost * ps.ps_availqty) as value
from
  partsupp ps,
  supplier s,
  nation n
where
  ps.ps_suppkey = s.s_suppkey
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'GERMANY'
group by
  ps.ps_partkey having
    sum(ps.ps_supplycost * ps.ps_availqty) > (
      select
        sum(ps.ps_supplycost * ps.ps_availqty) * 0.00001
      from
        partsupp ps,
        supplier s,
        nation n
      where
        ps.ps_suppkey = s.s_suppkey
        and s.s_nationkey = n.n_nationkey
        and n.n_name = 'GERMANY'
    )
order by
  value desc;
.shell sleep 0.3
.print __ITER__ 5
select
  ps.ps_partkey,
  sum(ps.ps_supplycost * ps.ps_availqty) as value
from
  partsupp ps,
  supplier s,
  nation n
where
  ps.ps_suppkey = s.s_suppkey
  and s.s_nationkey = n.n_nationkey
  and n.n_name = 'GERMANY'
group by
  ps.ps_partkey having
    sum(ps.ps_supplycost * ps.ps_availqty) > (
      select
        sum(ps.ps_supplycost * ps.ps_availqty) * 0.00001
      from
        partsupp ps,
        supplier s,
        nation n
      where
        ps.ps_suppkey = s.s_suppkey
        and s.s_nationkey = n.n_nationkey
        and n.n_name = 'GERMANY'
    )
order by
  value desc;
