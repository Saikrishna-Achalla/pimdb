CREATE VIEW lineitem AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/part.0.parquet']);
CREATE VIEW supplier AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/lineitem/*.parquet', tier='gpu', name='lineitem', cols=['l_suppkey','l_extendedprice','l_discount','l_shipdate']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/supplier/*.parquet', tier='gpu', name='supplier', cols=['s_suppkey','s_name','s_address','s_phone']);
.print __PIN_END__
.mode csv
.timer on
.print __ITER__ 1
with revenue_view as (
  select
    l_suppkey as supplier_no,
    sum(l_extendedprice * (1 - l_discount)) as total_revenue
  from
    lineitem
  where
    l_shipdate >= date '1993-05-01'
    and l_shipdate < date '1993-08-01'
  group by
    l_suppkey
)

select
  s.s_suppkey,
  s.s_name,
  s.s_address,
  s.s_phone,
  r.total_revenue
from
  supplier s,
  revenue_view r
where
  s.s_suppkey = r.supplier_no
  and r.total_revenue = (
    select
      max(total_revenue)
    from
      revenue_view
  )
order by
  s.s_suppkey;
.print __ITER__ 2
with revenue_view as (
  select
    l_suppkey as supplier_no,
    sum(l_extendedprice * (1 - l_discount)) as total_revenue
  from
    lineitem
  where
    l_shipdate >= date '1993-05-01'
    and l_shipdate < date '1993-08-01'
  group by
    l_suppkey
)

select
  s.s_suppkey,
  s.s_name,
  s.s_address,
  s.s_phone,
  r.total_revenue
from
  supplier s,
  revenue_view r
where
  s.s_suppkey = r.supplier_no
  and r.total_revenue = (
    select
      max(total_revenue)
    from
      revenue_view
  )
order by
  s.s_suppkey;
.print __ITER__ 3
with revenue_view as (
  select
    l_suppkey as supplier_no,
    sum(l_extendedprice * (1 - l_discount)) as total_revenue
  from
    lineitem
  where
    l_shipdate >= date '1993-05-01'
    and l_shipdate < date '1993-08-01'
  group by
    l_suppkey
)

select
  s.s_suppkey,
  s.s_name,
  s.s_address,
  s.s_phone,
  r.total_revenue
from
  supplier s,
  revenue_view r
where
  s.s_suppkey = r.supplier_no
  and r.total_revenue = (
    select
      max(total_revenue)
    from
      revenue_view
  )
order by
  s.s_suppkey;
.print __ITER__ 4
with revenue_view as (
  select
    l_suppkey as supplier_no,
    sum(l_extendedprice * (1 - l_discount)) as total_revenue
  from
    lineitem
  where
    l_shipdate >= date '1993-05-01'
    and l_shipdate < date '1993-08-01'
  group by
    l_suppkey
)

select
  s.s_suppkey,
  s.s_name,
  s.s_address,
  s.s_phone,
  r.total_revenue
from
  supplier s,
  revenue_view r
where
  s.s_suppkey = r.supplier_no
  and r.total_revenue = (
    select
      max(total_revenue)
    from
      revenue_view
  )
order by
  s.s_suppkey;
