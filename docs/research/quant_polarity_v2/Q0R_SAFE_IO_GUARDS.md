# Q.0-R Safe I/O Guards

Every Q.0-R market operation requires a frozen `MarketIOAuthorization`. The
capability binds one clean root, a frozen instrument subset, inclusive date
bounds, an exact partition set, and one operation type.

The guard validates dates and instruments before path construction. It permits
only the six frozen instruments and the inclusive 2015-01-01 through 2022-12-31
window. Paths are generated from exact instrument, side, year, and month
partitions. Recursive discovery, parent traversal, wildcards, unplanned
partitions, unsafe leaf names, and symlink or junction crossings are rejected.

Provider authorization is separate from read, write, and stat capabilities.
Atomic writes hash the temporary payload before promotion. No API in the module
performs recursive market-data discovery.

Certification: 15 focused tests passed; targeted Ruff and mypy passed; the real
new clean root passed external, empty, and reparse-point validation.
