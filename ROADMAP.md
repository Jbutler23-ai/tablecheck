# Proposed next work

These are rough development estimates, not logged hours or commitments. The current starter checks one CSV at a time. Each item needs design, implementation, tests, and documentation; the ranges include that work.

| Proposed feature | Useful result | Estimated effort |
| --- | --- | --- |
| Cross-table references | Declare primary keys and foreign keys, report duplicate keys and missing targets, and define handling for optional references. | 8–12 hours |
| Multi-table project configuration | Check a named set of tables from one command, resolve paths relative to a config, detect config mistakes, and summarize results across files. | 5–8 hours |
| Row constraints | Add unique and composite keys, conditional required fields, and comparisons between fields through a small declarative format. Avoid executing expressions from data. | 8–12 hours |
| Reports and integration | Version the JSON report format, add report-file output and a documented CI example, and test deterministic output and failure handling. | 5–8 hours |
| Profiling and performance | Build synthetic large-file cases, measure memory and time, bound retained issues, and evaluate streaming summaries without losing total counts. | 5–9 hours |

Total proposed work: **31–49 hours**. Actual time depends on the chosen behavior and findings during testing. Start with reference rules and project configuration together because their interfaces overlap. Exact decimal validation, additional delimiters, and configurable field limits can be considered after those interfaces settle.
