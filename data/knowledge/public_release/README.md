# Reference records for checks (data/knowledge/public_release/)

Records read by the published dataset build (`scripts/release/build_release_all.sh`) when it checks the published coordinates and when it keeps public IDs stable. They hold only values that can be published. The coordinates themselves come from `data/knowledge/places/` (the coordinate tables).

| File or folder | Contents | Read by |
|---|---|---|
| `public_points.csv` | Extract of publishable point sources (N02-25 [present-day railways], Location Reference Information, Historical Place Names Data, GeoNames, etc.) | the coordinate gate, step 4e (`scripts/release/coord_refs.py`, `scripts/release/check_coord_allowlist.py`) |
| `verified_geocoder_coincidences.csv` | Values equal to coordinates from an earlier automatic geocoder that were also confirmed with a publishable source, with the reason | the coordinate gate, step 4e (check D) |
| `verified_coordinates.csv` | Coordinates checked by hand that cannot be matched automatically (for example, a value read with a typo in the cited source corrected), with the source and the reason | the coordinate gate, step 4e (check D) |
| `id_registry/` | Registry of public IDs of stations, parent stations, routes and trips, kept the same across versions: `registry.csv` (the IDs), `renames.csv` (old and new keys of renamed entries that keep their IDs), `parent_station_children.csv` (the child stops of each parent station) | the published dataset build (`scripts/release/stable_ids.py`) |
