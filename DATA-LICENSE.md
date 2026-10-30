# Data license

The code in this repository is MIT licensed (see [LICENSE](LICENSE)). The place data is not.

`cities/*/spots.json` and `data/tagged.json` are derived from OpenStreetMap (© OpenStreetMap
contributors) combined with NYC Open Data restaurant inspection records and Neighborhood Tabulation
Areas. As a derivative database of OpenStreetMap they are available under the Open Database License
(ODbL 1.0): https://opendatacommons.org/licenses/odbl/

If you reuse these files, credit OpenStreetMap contributors and share any changes under the same
license.

## Open place lists ("Somewhere else" cities)

The files on the `places-data` branch (served at https://cdn.jsdelivr.net/gh/marinasofia/plan-committee@places-data/)
are built every month by `pipeline/build_places.py` from Overture Maps Places (https://overturemaps.org) and
`places/edits.json`. Overture's sources are licensed CDLA-Permissive-2.0, Apache-2.0 (Foursquare Open Source
Places, Copyright 2024 Foursquare Labs, Inc.; we filtered and reformatted it) and CC0-1.0 (AllThePlaces).
Anyone may use and share them: keep the notice in that branch's README and credit "Overture Maps Foundation".
`places/cities.json` comes from Overture's divisions, which are derived from OpenStreetMap (ODbL).
