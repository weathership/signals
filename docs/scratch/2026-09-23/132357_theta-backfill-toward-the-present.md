# Theta backfill walks toward the present

`just theta-backfill` now queues the earliest UTC day first and each next
day toward the present. A missed week starts on that week's first day.
`--latest-first` is the old order. The week in progress stays on Monday
06:00. Do not open it as one out-of-band LIGHT run.

The objective those increments serve is Gaius's: the best OWL-grounded
SKOS-in-Qdrant aperture for the week-or-longer window, still effective in
backtesting on the accumulated corpus. See
`gaius/docs/scratch/2026-09-23/132357_theta-objective-and-backfill-order.md`.
