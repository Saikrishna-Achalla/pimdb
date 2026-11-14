CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
CREATE VIEW customer AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/customer/part.0.parquet']);
.print __PIN_BEGIN__
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/customer/*.parquet', tier='gpu', name='customer', cols=['c_custkey','c_phone','c_acctbal']);
CALL pin_table('/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/*.parquet', tier='gpu', name='orders', cols=['o_custkey']);
.print __PIN_END__
.mode csv
.timer on
.print __ITER__ 1
select
  cntrycode,
  count(*) as numcust,
  sum(c_acctbal) as totacctbal
from
  (
    select
      substring(c_phone from 1 for 2) as cntrycode,
      c_acctbal
    from
      customer c
    where
      substring(c_phone from 1 for 2) in
        ('24', '31', '11', '16', '21', '20', '34')
      and c_acctbal > (
        select
          avg(c_acctbal)
        from
          customer
        where
          c_acctbal > 0.00
          and substring(c_phone from 1 for 2) in
            ('24', '31', '11', '16', '21', '20', '34')
      )
      and not exists (
        select
          *
        from
          orders o
        where
          o.o_custkey = c.c_custkey
      )
  ) as custsale
group by
  cntrycode
order by
  cntrycode;
.print __ITER__ 2
select
  cntrycode,
  count(*) as numcust,
  sum(c_acctbal) as totacctbal
from
  (
    select
      substring(c_phone from 1 for 2) as cntrycode,
      c_acctbal
    from
      customer c
    where
      substring(c_phone from 1 for 2) in
        ('24', '31', '11', '16', '21', '20', '34')
      and c_acctbal > (
        select
          avg(c_acctbal)
        from
          customer
        where
          c_acctbal > 0.00
          and substring(c_phone from 1 for 2) in
            ('24', '31', '11', '16', '21', '20', '34')
      )
      and not exists (
        select
          *
        from
          orders o
        where
          o.o_custkey = c.c_custkey
      )
  ) as custsale
group by
  cntrycode
order by
  cntrycode;
.print __ITER__ 3
select
  cntrycode,
  count(*) as numcust,
  sum(c_acctbal) as totacctbal
from
  (
    select
      substring(c_phone from 1 for 2) as cntrycode,
      c_acctbal
    from
      customer c
    where
      substring(c_phone from 1 for 2) in
        ('24', '31', '11', '16', '21', '20', '34')
      and c_acctbal > (
        select
          avg(c_acctbal)
        from
          customer
        where
          c_acctbal > 0.00
          and substring(c_phone from 1 for 2) in
            ('24', '31', '11', '16', '21', '20', '34')
      )
      and not exists (
        select
          *
        from
          orders o
        where
          o.o_custkey = c.c_custkey
      )
  ) as custsale
group by
  cntrycode
order by
  cntrycode;
