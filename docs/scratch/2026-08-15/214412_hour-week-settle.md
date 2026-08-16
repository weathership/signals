# Hour × week Kudu ranges, settle after 4 weeks

Range unit = `epoch_hour`. Tablet width = 168 hours. HASH(e) unchanged.
Iceberg not hour-partitioned (product identity). 4-week watermark =
`week_start(now) - 4*168` then DROP that week as a unit.

13 tests green.
