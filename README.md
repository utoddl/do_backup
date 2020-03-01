# do_backup
Backups via rsync to locally attached external storage

The idea here is to have a backup script that lives on an external
drive that you use to backup multiple machines. A single config file
contains the details of what gets backed up from each machine. When you
attach your backup drive to your host, you run the script, it locates
itself, then the config file next to it (which may change from host to
host due to where the drive gets mounted), it identifies the hostname,
and does either an incremental or full backup, depending on the
threshholds you've set for each machine. Older backups and their log
files get pruned once you've reached your configured limit.

```
[utoddl@lappy do_backup]$ ./do_backup.py --help
usage: do_backup.py [-h] [--config CONFIGFILE] [--debug] [--dry-run]

Backup selected files

optional arguments:
  -h, --help            show this help message and exit
  --config CONFIGFILE, -c CONFIGFILE
                        path to YAML configuration file
  --debug, -d           print debug message to console
  --dry-run, -n         don't actually backup anything; report what would be
                        done
```
