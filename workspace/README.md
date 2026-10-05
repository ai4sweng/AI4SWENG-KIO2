# workspace

Default host-side mount point for code KIO2 should analyse — see the
`volumes:` entry in [`docker-compose.yml`](../docker-compose.yml).

Drop a repo (or symlink one) in here, then reference it inside a request as
`/workspace/<name>/...` (the container-side path), not the host path — KIO2
runs inside the container and cannot see anything outside this mount.

To mount a different folder instead (e.g. a sibling checkout), copy
[`.env.example`](../.env.example) to `.env` and set `KIO2_WORKSPACE`.

Everything in this folder except this file is gitignored.
