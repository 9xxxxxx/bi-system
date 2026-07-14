# Legacy Data Backup

`dashboard.db` is a local, ignored backup of the original SQLite database.
Its verified SHA256 is:

`53E578FE47CE432B81EA2DA12B1EA1FD4F6B1041989280A8B05DF4199280AF56`

Expected row counts are `dim_city=9`, `dz_data=50`, `metric_def=21`, and
`rk_data=140`. Recheck the hash and counts before using this file in migration
tests.
