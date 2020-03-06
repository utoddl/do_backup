#!/usr/bin/env python

import sys
import platform
import os
import io
import pprint
import pwd
import shutil
import argparse
import yaml
import logging
import re
import glob
from datetime import datetime
import subprocess


def parse_args():
    parser = argparse.ArgumentParser(description="Backup selected files")
    parser.add_argument(
        "--config", "-c", metavar="CONFIGFILE", help="path to YAML configuration file"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true", help="print debug message to console"
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="don't actually backup anything; report what would be done",
    )
    args = parser.parse_args()
    return args


def get_fs_type(path):
    completed = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", path],
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    if completed.returncode == 0:
        return completed.stdout.split(os.linesep)[0]
    else:
        return "unknown"


def get_partials(host, conf):
    partials = 0
    partials_file = os.path.join(conf["logs"]["dir"], ".partials")
    if os.path.isfile(partials_file):
        with open(partials_file, "r") as f:
            partials = int(f.readline())
        f.close()
    return partials


def set_partials(host, conf, partials):
    partials_file = os.path.join(conf["logs"]["dir"], ".partials")
    with open(partials_file, "w+") as f:
        f.write("{}\n".format(partials))
    f.close()
    return partials


def backup_host(host, conf, timestamp, dry_run):
    bkl = logging.getLogger("bk")
    if os.path.exists(conf["target_dir"]):
        if not os.path.isdir(conf["target_dir"]):
            bkl.error("{} is not a directory; exiting.\n".format(conf["target_dir"]))
            sys.exit(1)
    elif not dry_run:
        os.makedirs(conf["target_dir"], mode=0o777, exist_ok=False)

    partials = get_partials(host, conf)
    if partials == 0 or partials % conf["max_partials"] != 0:
        bktype = "Incremental"
    else:
        bktype = "Full"

    for bk in conf["data"]:
        target = os.path.join(conf["target_dir"], timestamp, bk["dst"])

        globstr = os.path.join(conf["target_dir"], "*", bk["dst"])
        bkl.debug("globstr: {}".format(globstr))

        bkups = glob.glob(globstr)
        bkups.sort(reverse=True)
        bkl.debug("len(bkups): {}".format(len(bkups)))

        if len(bkups) > 0 and bktype == "Incremental":
            lnkdst = ["--link-dest", bkups[0]]
        else:
            lnkdst = []

        bkl.info("=== {} backup of '{}' to '{}'. ===".format(bktype, bk["src"], target))
        if not dry_run:
            os.makedirs(target)
        srcfstype = get_fs_type(bk["src"])
        if not dry_run:
            dstfstype = get_fs_type(target)
        else:
            dstfstype = get_fs_type(os.path.split(conf["target_dir"])[0])

        bkl.debug("src fs type: {}, dst fs type: {}".format(srcfstype, dstfstype))
        rsync = ["rsync"]
        opts = 0
        for opt_map in conf["rsync_opt_map"]:
            if (
                srcfstype in opt_map["src_fs_type"]
                and dstfstype in opt_map["dst_fs_type"]
            ):
                for opt in opt_map["options"]:
                    opts += 1
                    rsync.append(opt)
                break

        if opts == 0:
            bkl.error(
                "No rsync options found for {} -> {}; exiting.".format(
                    srcfstype, dstfstype
                )
            )
            sys.exit(1)

        for ex in conf["excludes"]:
            rsync.append("--exclude")
            rsync.append(ex)

        for ld in lnkdst:
            rsync.append(ld)

        rsync.append(bk["src"] + "/" if not bk["src"].endswith("/") else bk["src"])
        rsync.append(target)

        bkl.debug(" ".join(rsync))

        if not dry_run:
            proc = subprocess.Popen(
                rsync, stdout=subprocess.PIPE, universal_newlines=True
            )
            for line in iter(proc.stdout.readline, ""):
                bkl.info(line.rstrip(os.linesep))

    # drwxrwxr-x. 2 utoddl utoddl 4096 Feb 29 18:05 backups/lappy/2020-02-29--18:05:12/neg
    # drwxrwxr-x. 7 utoddl utoddl 4096 Feb 24 20:26 backups/lappy/2020-02-29--18:09:12/neg
    # drwxrwxr-x. 7 utoddl utoddl 4096 Feb 24 20:26 backups/lappy/2020-02-29--18:09:24/neg
    # drwxrwxr-x. 7 utoddl utoddl 4096 Feb 24 20:26 backups/lappy/2020-02-29--18:09:41/neg
    # [utoddl@lappy do_backup]$ ls -ld bk_logs/*
    # total 1148
    # -rw-rw-r--. 1 utoddl utoddl    150 Feb 29 17:25 bk_logs/lappy/2020-02-29--17:25:16
    # -rw-rw-r--. 1 utoddl utoddl    150 Feb 29 17:30 bk_logs/lappy/2020-02-29--17:30:24
    # -rw-rw-r--. 1 utoddl utoddl    150 Feb 29 17:31 bk_logs/lappy/2020-02-29--17:31:02

    # prune extra 'backups/{host}/<timestamp>' directories,
    # then prune any 'bk_logs/{host}/<timestamp>.log' files that don't match a remaining directory.
    globstr = os.path.join(conf["target_dir"], "*")
    bkdirs = [
        d
        for d in glob.glob(globstr)
        if os.path.isdir(d) and re.search("/\d\d\d\d-\d\d-\d\d--\d\d:\d\d:\d\d", d)
    ]
    bkdirs.sort()
    while len(bkdirs) > conf["max_backups"]:
        runs_left = conf["max_tail"]
        to_delete = []
        for bk in range(0, len(bkdirs)):
            if runs_left > 0 and bk % conf["max_tail"] == 0:
                to_delete.append(bk)
                runs_left -= 1
        while len(to_delete) > 0:
            bk = to_delete.pop()
            bkl.info("Removing backup directory #{}: {}".format(bk, bkdirs[bk]))
            if not dry_run:
                shutil.rmtree(bkdirs[bk], ignore_errors=True)
            bkdirs.pop(bk)

    bktimestamps = [
        re.sub(".*(\d\d\d\d-\d\d-\d\d--\d\d:\d\d:\d\d).*", "\\1", d) for d in bkdirs
    ]
    bkl.debug("timestamps: {}".format(bktimestamps))
    globstr = os.path.join(conf["logs"]["dir"], "*")
    bk_logs = [
        f
        for f in glob.glob(globstr)
        if os.path.isfile(f)
        and re.search("/" + host + "-\d\d\d\d-\d\d-\d\d--\d\d:\d\d:\d\d", f)
    ]
    bk_logs.sort()
    for bkf in bk_logs:
        ts = re.search("(\d\d\d\d-\d\d-\d\d--\d\d:\d\d:\d\d)", bkf)
        if ts and ts.group(1) not in bktimestamps:
            bkl.info("Removing log file {}".format(bkf))
            if not dry_run:
                os.unlink(bkf)

    if not dry_run:
        if bktype == "Incremental":
            set_partials(host, conf, partials + 1)
        else:
            set_partials(host, conf, 0)


def main():
    pp = pprint.PrettyPrinter(indent=4)
    args = parse_args()
    (app_path, app_name) = os.path.split(os.path.realpath(__file__))
    if args.config:
        app_conf = args.config
    else:
        for ext in [".yaml", ".yml"]:
            app_conf = os.path.join(app_path, os.path.splitext(app_name)[0] + ext)
            if os.path.isfile(app_conf):
                break

    if args.debug:
        print(
            "app_path: {}\napp_name: {}\napp_conf: {}\n".format(
                app_path, app_name, pp.pformat(app_conf)
            )
        )

    with open(app_conf, "r") as stream:
        try:
            config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)

    if "uid" not in config:
        config["uid"] = "root"
    if "target_dir" not in config:
        config["target_dir"] = "backups"
    if "excludes" not in config:
        config["excludes"] = []
    if "rsync_opt_map" not in config:
        config["rsync_opt_map"] = [
            {"src_fs_type": [], "dst_fs_type": [], "options": []}
        ]
    if "max_backups" not in config:
        config["max_backups"] = 4
    if "max_partials" not in config:
        config["max_partials"] = 4
    if "max_tail" not in config:
        config["max_tail"] = 1
    if "hosts" not in config:
        config["hosts"] = {}
    if "logs" not in config:
        config["logs"] = {"level": "info", "dir": "bk_logs"}
    if "level" not in config["logs"]:
        config["logs"]["level"] = "info"
    if "dir" not in config["logs"]:
        config["logs"]["dir"] = "bk_logs"

    if args.debug:
        print("{}".format(pp.pformat(config)))

    if platform.node() in config["hosts"]:
        host = platform.node()
    elif platform.node().split(".", 1)[0] in config["hosts"]:
        host = platform.node().split(".", 1)[0]
    else:
        print(
            "Host '{}' is not configured in '{}'; exiting.".format(
                platform.node(), app_conf
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    for override in [
        "rsync_opt_map",
        "excludes",
        "uid",
        "target_dir",
        "max_backups",
        "max_partials",
        "max_tail",
        "logs",
    ]:
        if override in config and override not in config["hosts"][host]:
            config["hosts"][host][override] = config[override]

    if int(config["hosts"][host]["max_tail"]) * int(
        config["hosts"][host]["max_tail"]
    ) > int(config["hosts"][host]["max_backups"]):
        print(
            "Host '{}' max_tail ({}) is too large for max_backups ({}); exiting.".format(
                host,
                config["hosts"][host]["max_tail"],
                config["hosts"][host]["max_backups"],
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    # Make host's logs dir and target_dir absolute paths.
    if not os.path.isabs(config["hosts"][host]["logs"]["dir"]):
        config["hosts"][host]["logs"]["dir"] = os.path.join(
            app_path, config["hosts"][host]["logs"]["dir"]
        )

    if not os.path.isabs(config["hosts"][host]["target_dir"]):
        config["hosts"][host]["target_dir"] = os.path.join(
            app_path, config["hosts"][host]["target_dir"]
        )

    # Ensure host's logs dir and target_dir end with '/{host}'
    if not config["hosts"][host]["logs"]["dir"].endswith(host):
        config["hosts"][host]["logs"]["dir"] = os.path.join(
            config["hosts"][host]["logs"]["dir"], host
        )

    if not config["hosts"][host]["target_dir"].endswith(host):
        config["hosts"][host]["target_dir"] = os.path.join(
            config["hosts"][host]["target_dir"], host
        )

    if args.debug:
        print(
            "Configuration for host '{}'\n{}".format(
                host, pp.pformat(config["hosts"][host])
            )
        )

    euid = pwd.getpwuid(os.geteuid())
    if config["hosts"][host]["uid"] != euid.pw_name:
        print(
            "Required user is '{}' but running as '{}'; exiting.".format(
                config["hosts"][host]["uid"], euid.pw_name
            ),
            file=sys.stderr,
        )
        sys.exit(2)

    timestamp = datetime.today().strftime("%Y-%m-%d--%H:%M:%S")
    logger = logging.getLogger("bk")
    logger.setLevel(logging.DEBUG)

    os.makedirs(config["hosts"][host]["logs"]["dir"], mode=0o777, exist_ok=True)

    # create file handler which logs to the backup log files
    if not args.dry_run:
        fh = logging.FileHandler(
            os.path.join(
                config["hosts"][host]["logs"]["dir"], host + "-" + timestamp + ".log"
            )
        )
        fh.setLevel(
            getattr(logging, config["hosts"][host]["logs"]["level"].upper(), None)
        )

    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if args.debug else logging.INFO)

    # create formatter and add it to the handlers
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    if not args.dry_run:
        fh.setFormatter(formatter)

    # add the handlers to the logger
    logger.addHandler(ch)
    if not args.dry_run:
        logger.addHandler(fh)

    backup_host(host, config["hosts"][host], timestamp, args.dry_run)


if __name__ == "__main__":
    if sys.version_info < (3,):
        sys.stderr.write("You need python 3 or later to run this script\n")
        sys.exit(1)
    main()
