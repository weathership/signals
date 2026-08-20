# signals.target complete refresh

`just signals-restart` → `scripts/systemd_target_refresh.sh`:
reset-failed, `systemctl stop` then `start` the target, then
`systemd_target_verify.sh`.

`signals-refresh.service` is WantedBy the target so a native
`systemctl restart signals.target` also runs the verify after members
finish their start jobs.

Current lab: atelier.service failed (`:50251`); verify exits 1.
