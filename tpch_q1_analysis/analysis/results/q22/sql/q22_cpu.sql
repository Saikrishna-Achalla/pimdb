CREATE VIEW orders AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/orders/part.0.parquet']);
CREATE VIEW customer AS SELECT * FROM read_parquet(['/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1/customer/part.0.parquet']);
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
.print __ITER__ 4
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
.print __ITER__ 5
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
.print __ITER__ 6
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
.print __ITER__ 7
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
.print __ITER__ 8
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
.print __ITER__ 9
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
.print __ITER__ 10
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
.print __ITER__ 11
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
.print __ITER__ 12
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
.print __ITER__ 13
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
.print __ITER__ 14
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
.print __ITER__ 15
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
