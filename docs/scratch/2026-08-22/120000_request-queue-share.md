# RequestQueueShare + ListQueueShareRequests

Pin `signals-protocol` `9649662`. Persist peer WRK occupancy under
`SIGNALS_YK_PROJECTION_ROOT/shares/*.json`. Merge leftover floors
(extract vs light/medium) against GPU max 6; PromoteScratch applies
yunikorn-configs. SUPERSEDED on same-peer leftover swap. REJECTED if
two peers would exceed 6. SHAREFAIL only on persist I/O.
