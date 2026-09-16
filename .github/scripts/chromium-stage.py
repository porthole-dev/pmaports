#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""One stage of the staged chromium build (.github/workflows/chromium.yml).
Run through run-pmbootstrap.sh; design in .github/CHROMIUM.md.

  chromium-stage.py prep              build.yml's build of chromium, stopped
                                      when ninja starts: sources fetched,
                                      unpacked, patched, gn gen done
  chromium-stage.py build DEADLINE    abuild's build part until DEADLINE
                                      (epoch seconds), then stop ninja
  chromium-stage.py package           abuild's build, check and rootpkg parts

build and package re-enter the work directory that prep left behind, with
the environment pmbootstrap gives abuild (pmb.build.backend.abuild_env), and
run the parts of abuild's own sequence that are left:

  prep     validate builddeps clean fetch unpack prepare mkusers build(stopped)
  build    build (ninja resumes from out/bld/.ninja_log)
  package  build (nothing left) check rootpkg

check is in that list only where abuild's own want_check() would put it, see
want_check() below.

Writes /work/chromium/result.json for chromium-state.sh.
"""
import json
import multiprocessing
import os
import pathlib
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
import packages  # noqa: E402  (.github/scripts/packages.py)

import pmb.build.backend  # noqa: E402
import pmb.build.autodetect  # noqa: E402
import pmb.build.other  # noqa: E402
import pmb.chroot  # noqa: E402
import pmb.config  # noqa: E402
import pmb.helpers.mount  # noqa: E402
import pmb.helpers.pmaports  # noqa: E402
import pmb.parse  # noqa: E402
from pmb.core.arch import Arch  # noqa: E402
from pmb.core.context import get_context  # noqa: E402
from pmb.types import CrossCompile  # noqa: E402

PKG = "chromium"
STATE = packages.WORK / "chromium"
CONFIG = STATE / "pmbootstrap_v3.cfg"
ARCH = Arch.aarch64
# A resumed stage may re-run the edges the previous stage interrupted and a
# few that always run. A restore that lost mtimes re-runs tens of thousands.
REBUILD_LIMIT = 1000


def out_dir() -> pathlib.Path | None:
    found = sorted((packages.WORK / "chroot_native/home/pmos/build/src").glob(f"{PKG}-*/out/bld"))
    return found[0] if found else None


def records(out: pathlib.Path | None) -> dict[str, str]:
    """samurai's .ninja_log: output path -> recorded mtime, last record wins."""
    ret = {}
    log = out / ".ninja_log" if out else None
    if log and log.exists():
        for line in log.read_text(errors="replace").splitlines():
            fields = line.split("\t")
            if len(fields) == 5:
                ret[fields[3]] = fields[2]
    return ret


def chromium_ninja() -> list[str]:
    """PIDs of ninja running in chromium's out/bld (samurai chdirs there).
    Not any ninja: prep first builds the forked build dependencies that are
    not published, and their meson builds run ninja too."""
    pids = subprocess.run(["pgrep", "-x", "ninja"], capture_output=True, text=True).stdout.split()
    return [pid for pid in pids if f"/src/{PKG}-" in subprocess.run(
        ["sudo", "readlink", f"/proc/{pid}/cwd"], capture_output=True, text=True).stdout]


class Watchdog(threading.Thread):
    """Stops ninja with SIGTERM when the deadline passes (prep: as soon as it
    runs), or when it rebuilds outputs the restored log already records.

    samurai forwards the signal to its jobs and exits; an interrupted job
    writes no .ninja_log record, so the next stage runs it again instead of
    trusting a partial output (samurai build.c isdirty(): "no record in
    .ninja_log")."""

    def __init__(self, deadline: float | None, before: dict[str, str]):
        super().__init__(daemon=True)
        self.deadline, self.before = deadline, before
        self.reason: str | None = None
        self.rebuilt = 0
        self.done = threading.Event()

    def stop(self, reason: str) -> None:
        self.reason = reason
        print(f"::notice::stopping ninja: {reason}", flush=True)
        for pid in chromium_ninja():
            subprocess.run(["sudo", "kill", "-TERM", pid], check=False)

    def run(self) -> None:
        while not self.done.wait(2 if self.deadline is None else 30):
            if self.deadline is None:
                if chromium_ninja():
                    self.stop("sources are prepared")
                    return
                continue
            now = records(out_dir())
            self.rebuilt = sum(1 for p, m in now.items() if p in self.before and self.before[p] != m)
            if self.rebuilt > REBUILD_LIMIT:
                self.stop(f"{self.rebuilt} outputs of earlier stages are being rebuilt:"
                          " the restored state is not consistent")
                return
            if time.time() >= self.deadline:
                self.stop("stage deadline")
                return


def want_check(apkbuild: dict, env: dict) -> bool:
    """abuild's own want_check(): it drops the check part when CBUILD != CHOST
    or when options has !check (abuild.in want_check(), build_abuildrepo()).
    Naming the parts by hand bypasses that -- abuild runs any part it is
    given -- and the APKBUILD's build() builds the five unit test binaries
    under the same want_check(), so a check part where abuild would not have
    one fails on a test binary that was never built.

    Of the two cross values this workflow can produce, pmbootstrap sets CHOST
    only for cross-native2 (pmb.build.backend.abuild_env), the x86_64 runner;
    the native arm64 runner leaves CBUILD == CHOST and runs every suite."""
    return "CHOST" not in env and "!check" not in apkbuild["options"]


def enter() -> tuple[CrossCompile, dict, dict]:
    """pmbootstrap's context for the work directory prep left behind."""
    sys.argv = ["pmbootstrap.py", "--config", str(CONFIG), "--aports", str(packages.ROOT),
                "--details-to-stdout", "--timeout", "3600", "chroot"]
    pmb.parse.arguments()
    pmb.config.require_programs()
    context = get_context()
    # Prep ran on a runner of the same arch, but maybe not with the same CPUs.
    context.config.jobs = multiprocessing.cpu_count()
    apkbuild = pmb.helpers.pmaports.get(PKG)
    cross = pmb.build.autodetect.crosscompile(apkbuild, ARCH)
    chroot = cross.build_chroot(ARCH)
    pmb.chroot.init(chroot)
    pmb.build.other.configure_abuild(chroot)
    # pmbootstrap creates the directories that /home/pmos's cache symlinks
    # point at only while it creates a chroot; init() returns early for one
    # that exists. chromium-state.sh stores the prep layer without the cache
    # contents (--exclude='./cache_*/*'), so in a restored chroot the targets
    # that live *inside* a cache bind mount are gone and their symlinks
    # dangle: /home/pmos/.cache/go-build -> /mnt/pmbootstrap/go/gocache (and
    # the three cargo ones). os.MkdirAll() returns EEXIST on a dangling
    # symlink, which is Go's "failed to initialize build cache at
    # /home/pmos/.cache/go-build: ... file exists" that broke dawn's
    # generate_sources in run 35075286983. Recreate only what is missing: a
    # target that exists as something else still fails where it is used.
    for target in pmb.config.chroot_home_symlinks:
        if not (chroot / target).is_dir():
            print(f"::notice::recreating the cache directory {target}", flush=True)
            pmb.chroot.root(["mkdir", "-p", target], chroot)
            pmb.chroot.root(["chown", "pmos:pmos", target], chroot)
    # run_abuild() gives $WORK/packages to the chroot's build user, but only
    # when it creates the directory. The restored one exists and belongs to
    # the runner: run-pmbootstrap.sh hands the work directory back to
    # HOST_UID when the prep container exits, and the layer keeps that owner.
    # abuild (uid 12345) writes the apks there in the package stage.
    uid = pmb.config.chroot_uid_user
    subprocess.run(["sudo", "chown", "-R", f"{uid}:{uid}", str(context.config.work / "packages")],
                   check=True)
    # What pmb.build.backend.run_abuild() sets up before running abuild.
    if cross == CrossCompile.CROSS_NATIVE2:
        pmb.helpers.mount.bind(cross.host_chroot(ARCH).path, chroot / "mnt/sysroot", umount=True)
    pmb.build.backend.mount_pmaports(chroot)
    return cross, pmb.build.backend.abuild_env(context, ARCH, cross, 0), apkbuild


def abuild(parts: list[str], cross: CrossCompile, env: dict) -> int:
    try:
        pmb.chroot.user(["abuild", "-d", "-D", "postmarketOS", *parts], cross.build_chroot(ARCH),
                        pathlib.Path("/home/pmos/build"), env=env)
        return 0
    except Exception as e:  # pmbootstrap's CommandFailedError, or its timeout
        print(f"abuild {' '.join(parts)}: {e}", flush=True)
        return 1


def main() -> int:
    mode, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if mode not in ("prep", "build", "package") or len(args) != (mode == "build"):
        print(__doc__)
        return 64
    subprocess.run(["sudo", "mkdir", "-p", str(STATE)], check=True)
    subprocess.run(["sudo", "chown", f"{os.getuid()}", str(STATE)], check=True)
    before = records(out_dir())
    result = {"mode": mode, "records_before": len(before)}

    if mode == "prep":
        # packages.py's own main() setup, then the exact build.yml build.
        sys.argv = ["pmbootstrap.py", "--aports", str(packages.ROOT), "chroot"]
        pmb.parse.arguments()
        get_context()
        dog = Watchdog(None, before)
        dog.start()
        try:
            rc = packages.cmd_build(PKG)
        except subprocess.CalledProcessError:
            rc = 1
        dog.done.set()
        config = pathlib.Path.home() / ".config/pmbootstrap_v3.cfg"
        CONFIG.write_text(config.read_text())
        ok = dog.reason is not None and out_dir() is not None
        if not ok:
            print("::error::prep did not reach ninja" if rc else "::error::prep built the whole package")
    else:
        cross, env, apkbuild = enter()
        deadline = float(args[0]) if mode == "build" else None
        dog = Watchdog(deadline, before) if mode == "build" else None
        if dog:
            dog.start()
        if mode == "build":
            parts = ["build"]
        else:
            check = ["check"] if want_check(apkbuild, env) else []
            if not check:
                print(f"::notice::abuild skips check for cross={cross}"
                      f" and options={' '.join(apkbuild['options'])}", flush=True)
            parts = ["build", *check, "rootpkg"]
            result["parts"] = parts
        rc = abuild(parts, cross, env)
        if dog:
            dog.done.set()
            result["rebuilt"] = dog.rebuilt
        # A deadline stop is the expected end of a stage; a consistency stop
        # or any other failure is not, but its progress is still valid.
        ok = rc == 0 or (dog is not None and dog.reason == "stage deadline")
        result["done"] = rc == 0
        if dog and dog.reason and dog.reason != "stage deadline":
            result["error"] = dog.reason

    out = out_dir()
    result.update(ok=ok, returncode=rc, stopped=dog.reason if dog else None,
                  records_after=len(records(out)),
                  out_dir=str(out.relative_to(packages.WORK)) if out else None)
    (STATE / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
