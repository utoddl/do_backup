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

_This script was written after the demise python2 and is unapologetically
python3-only._

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

## Configuration
By default, the script looks for a config file in the same directory as
itself. So, if you call the script `do_backup.py`, it will look for
`do_backup.yaml` or `do_backup.yml` in the same directory.

The config file consists of several "top level" variables that act
as defaults for each host, as well as specific settings for each host.

### Logging
```
logs:
  level: info
  dir: bk_logs
```
The log level could be 'debug', 'info', 'warning', 'error', or
'critical', but in practice only 'debug' and 'info' are useful. `dir`
is either an absolute or relative (to the script) path to a directory
to put individual logs of each backup run. This doesn't define the file
names; they will be named "{host}-{timestamp}.log" within the
directory. In addition to the logs, a file named "{host}-partials" will
be created which records how many partial or incremental backups have
been taken for a give host since the last full backup. These backup log
files are deleted when their corresponding backups are removed.

### target_dir
```
target_dir: backups
```
This specifies a directory, either an absolute path or relative to the
script, into which backups are made. Within this directory, additional
subdirectories will be made named `{host}/{timestamp}` where the
timestamp indicates the local time the backup run was initiated.

### Backup Counts and Retention
```
max_backups: 17  # older backups get removed
max_partials: 5  # incrementals between full backups
max_tail: 4      # controls how older backups are removed.
```
After taking the `max_backups`+1 backups, `max_tail` backups are
deleted along with their corresponding log files. `max_tail` defaults
to 1, but its square should always be less than `max_backups`.
Given the example above, lets call the backups `A` through `R`, where
`A` is the oldest backup. `R` is the 18th, which is one greater than
`max_backups`, so we delete `max_tail` older backups, selecting the
first in each run on `max_tail` backups. Here are two examples showing
the remaining backups after `max_backups` is exceeded.
```
               max_tail=3                             max_tail=4                           
18 backups: ABCDEFGHIJKLMNOPQR                     ABCDEFGHIJKLMNOPQR
   becomes:  BC EF HIJKLMNOPQR                      BCD FGH JKL NOPQR

22 backups: BC EF HIJKLMNOPQRSTUV                  BCD FGH JKL NOPQRSTUV
   becomes:  C E  HI KLMNOPQRSTUV                   CD F H JK  NOP RSTUV

26 backups: C E  HI KLMNOPQRSTUVWXYZ               CD F H JK  NOP RSTUVWXYZ
   becomes:   E  H  KL NOPQRSTUVWXYZ                D F H  K  NO  RST VWXYZ

30 backups: E  H  KL NOPQRSTUVWXYZabcd             D F H  K  NO  RST VWXYZabcd
   becomes:    H  K  NO QRSTUVWXYZabcd               F H  K   O  RS  VWX Zabcd

34 backups: H  K  NO QRSTUVWXYZabcdefgh            F H  K   O  RS  VWX Zabcdefgh
   becomes:    K  N  QR TUVWXYZabcdefgh              H  K   O   S  VW  Zab defgh

38 backups: K  N  QR TUVWXYZabcdefghijkl           H  K   O   S  VW  Zab defghijkl
   becomes:    N  Q  TU WXYZabcdefghijkl              K   O   S   W  Za  def hijkl
   
42 backups: N  Q  TU WXYZabcdefghijklmnop          K   O   S   W  Za  def hijklmnop
   becomes:    Q  T  WX Zabcdefghijklmnop              O   S   W   a  de  hij lmnop

46 backups: Q  T  WX Zabcdefghijklmnopqrst         O   S   W   a  de  hij lmnopqrst
   becomes:    T  W  Za cdefghijklmnopqrst             S   W   a   e  hi  lmn pqrst
```
So `max_tail` says not only how many old backups to delete, but also
to delete the first in each run of `max_tail` oldest backups.

### Excludes
```
excludes:
  - /**/.cache/
  - /**/.ccache/
  - /**/cache/
  - /**/Cache/
  - /dev/
  - /proc/
  - /run/
  - /sys/
```
Each of these is passed to `rsync` as the value of an `--exclude` parameter. See 
the `rsync` man pages.

### Rsync Flags Based on Src and Dst Filesystem Type
```
rsync_opt_map:
  - src_fs_type: ['ext2', 'ext3', 'ext4']
    dst_fs_type: ['ext4']
    options: ['-a', '-H', '-A', '-X', '-x', '-v' ]

  - src_fs_type: [ 'fat32', 'ntfs', 'unknown', 'ext2', 'ext3', 'ext4' ]
    dst_fs_type: ['ext4', 'tmpfs']
    options: ['-a', '-H', '-A',       '-x', '-v' ]
```
The `findmnt` program is used to determine the filesystem types of both the source
and destination of the `rsync` command. The `options` from the first `rsync_opt_map`
entry that matches both filesystem types are used. If no matching entries are found,
an error is reported and the script terminates.

### UID
```
uid: root
```
The script checks the name of the user it's running as, and exits with an error
if there's a mismatch.

### Hosts Specifications
```
hosts:
  bingo:        # the local host name
      excludes:
        - /dev/
        - /proc/
        - /run/
        - /sys/
        - /**/ImapMail/
        - /smb/todd/trailsong.img.*
        - /smb/todd/trailsong.tgz
      data:
        - src: /home
          dst:  home
        - src: /root
          dst:  root
        - src: /etc
          dst:  etc
        - src: /var/spool/imap
          dst:  var_spool_imap
        - src: /var/lib/imap
          dst:  var_lib_imap
  lappy:        # a second host name
    uid: utoddl
    data:
      - src: /home/utoddl/src/neg
        dst:                  neg
```
The `hosts` section defines what to backup on each host in its `data`
subsection. Typically `src` is an absolute path to be backed up, while
`dst` is a name (no directory delimiters) to which `src` will be copied
beneath `{backups}/{host}/{timestamp}/`.

Each host specification may override any of the outer level values that
it would otherwise inherit. So for example, above, the host `lappy`
runs its `rsync`s as the user `utoddl` rather than `root`.

If you choose to override an outer value, say `excludes` or
`rsync_opt_map`, you must specify it completely. There is no clever
merging of global and host-specific values.


