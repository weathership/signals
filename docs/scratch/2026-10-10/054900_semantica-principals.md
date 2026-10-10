# Semantica principals

`signals@DEV.VISTA.ZNDX.ORG` stays the Signals service principal (password and `signals.keytab`).

Added on the existing lab KDC, without a reset:

- `zndx@DEV.VISTA.ZNDX.ORG` — user principal. Semantica's web login username is `zndx`. Password matches the primary, same local-dev pattern as `signals`.
- `semantica@DEV.VISTA.ZNDX.ORG` — service principal for the Semantica warehouse FDW. Randkey in `.devenv/kdc/semantica.keytab`.

`kdc-init.sh` creates both on a fresh database and again when the database already exists. SPNEGO for the web app uses the existing `HTTP/tinybox.dev.vista.zndx.org` keytab and is optional.
