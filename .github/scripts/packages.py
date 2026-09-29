#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""CI steps for this branch's packages that need pmbootstrap.
Run through run-pmbootstrap.sh.

  packages.py lint                 apkbuild-lint and version bump, changed aports
  packages.py check-patches [--all]
                                   fetch and verify sources, unpack, apply patches
  packages.py select               aports to build -> /work/matrix.json
  packages.py build PKG            build one aport -> /work/packages/<repo>/aarch64
  packages.py outdated             forks that upstream packages outrank
                                   -> /work/outdated.md, /work/outdated.count

"Changed" means changed since $CI_MERGE_REQUEST_DIFF_BASE_SHA, the variable
pmaports' own .ci/lib/common.py reads; unset means nothing changed.

"Forked" means present in .github/maintained-aports.json, generated from
porthole profile/shared manifests. Git ancestry is not a maintenance inventory.
.github/packages.conf only marks heavy, excluded and unpublished aports.
"""
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request

import common  # pmaports .ci/lib
import pmb.config.pmaports
import pmb.parse
import pmb.parse.version
from pmb.core.arch import Arch
from pmb.core.context import get_context

ROOT = pathlib.Path(common.get_pmaports_dir())
GITHUB = ROOT / ".github"
WORK = pathlib.Path("/work")
ARCH = "aarch64"
PACKAGER = os.environ.get("PACKAGER", "")
# GitHub refuses a matrix of more than 256 jobs, and refuses it while the
# matrix expression is evaluated: the run then fails with no job to blame.
MAX_JOBS = 200


def excluded(pkg: str) -> bool:
    # Only the reviewed Taimen grant may open this exception. Keep the
    # default closed until its full scope is recorded by the maintainer.
    taimen = {"firmware-google-taimen", "firmware-google-taimen-fingerprint"}
    return pkg.startswith("firmware-") and not (
        pkg in taimen and os.environ.get("FIRMWARE_GRANT_TAIMEN") == "approved")


def tiers() -> dict[str, str]:
    ret = {}
    for line in (GITHUB / "packages.conf").read_text().splitlines():
        fields = line.split("#", 1)[0].split()
        if fields:
            tier, name = fields
            assert tier in ("heavy", "exclude", "unpublished"), f"packages.conf: unknown tier {tier}"
            ret[name] = tier
    return ret


def aport_dir(pkg: str) -> pathlib.Path | None:
    for pattern in (f"*/{pkg}", f"device/*/{pkg}", f"extra-repos/*/{pkg}"):
        for d in ROOT.glob(pattern):
            if (d / "APKBUILD").exists() and "archived" not in d.parts:
                return d
    return None


def is_systemd(d: pathlib.Path) -> bool:
    return d.relative_to(ROOT).parts[:2] == ("extra-repos", "systemd")


def apkbuild(d: pathlib.Path) -> dict:
    return pmb.parse.apkbuild(d / "APKBUILD", False, False)


def version(d: pathlib.Path) -> str:
    a = apkbuild(d)
    return f"{a['pkgver']}-r{a['pkgrel']}"


def changed(base: str | None = None) -> set[str]:
    """Aports changed since base (default: $CI_MERGE_REQUEST_DIFF_BASE_SHA)."""
    var = "CI_MERGE_REQUEST_DIFF_BASE_SHA"
    default = os.environ.get(var)
    if not (base or default):
        return set()
    os.environ[var] = base or default
    common.get_base_commit.cache_clear()
    # The checkouts have no blobs (filter blob:none) and no credentials: rename
    # detection between a deleted and an added file would download blobs and
    # fail. A moved aport is an added one here.
    common.run_git(["config", "diff.renames", "false"])
    try:
        return common.get_changed_packages(skip_archived=True)
    finally:
        if default is None:
            del os.environ[var]
        else:
            os.environ[var] = default
        common.get_base_commit.cache_clear()


def forks() -> set[str]:
    """Reviewed maintained inventory; rewritten history cannot identify forks."""
    from maintained import load
    return load(ROOT) - {p for p, t in tiers().items() if t == "exclude"}


def private_source(d: pathlib.Path) -> str | None:
    """The URL of a repository of this organization that the APKBUILD fetches
    from and that cannot be read anonymously (a private repository), or None.
    abuild downloads without credentials, so such a source cannot be fetched."""
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not owner:
        return None
    text = (d / "APKBUILD").read_text()
    for repo in sorted(set(re.findall(rf"https://github\.com/{re.escape(owner)}/[A-Za-z0-9._-]+", text))):
        try:
            with urllib.request.urlopen(urllib.request.Request(repo, method="HEAD"), timeout=30):
                pass
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return repo
        except (urllib.error.URLError, TimeoutError):
            pass  # a network problem is not a private repository; the fetch will say
    return None


def unavailable_source(pkg: str, d: pathlib.Path) -> bool:
    repo = private_source(d)
    if repo:
        print(f"::error::{pkg}: source {repo} is unavailable anonymously; "
              "publish the reviewed source or repair its URL before building")
    return bool(repo)


def pmbootstrap(*args: str) -> None:
    print("$ pmbootstrap " + " ".join(args), flush=True)
    common.run_pmbootstrap(["--details-to-stdout", *args])


def use_systemd(on: bool) -> None:
    """Build like the binary repository the aport belongs to: extra-repos/systemd
    with systemd, everything else without, as pmaports' own CI does. The
    service manager is only selectable with a UI that supports both."""
    pmbootstrap("config", "auto_zap_misconfigured_chroots", "yes")
    pmbootstrap("config", "ui", "phosh")
    pmbootstrap("config", "service_manager", "systemd" if on else "openrc")


def resolve(pkgs) -> list[tuple[str, pathlib.Path]]:
    """(pkg, aport dir), stock repository first so the chroot is zapped once."""
    found = []
    for pkg in sorted(pkgs):
        d = aport_dir(pkg)
        if excluded(pkg):
            print(f"{pkg}: firmware grant not enabled; not built or published")
        elif d is None:
            print(f"{pkg}: no aport (deleted or archived), skipping")
        else:
            found.append((pkg, d))
    return sorted(found, key=lambda item: is_systemd(item[1]))


def cmd_lint() -> int:
    import apkbuild_linting
    import check_changed_versions

    os.environ["CUSTOM_VALID_OPTIONS"] = " ".join(
        apkbuild_linting.custom_valid_options + apkbuild_linting.get_kconfigcheck_categories()
    )
    base = os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA")
    ret = 0
    for pkg, d in resolve(changed()):
        rel = str(d.relative_to(ROOT))
        # Unlike pmaports' CI, temp/ is linted too: that is where forks live.
        if subprocess.run(["apkbuild-lint", f"{rel}/APKBUILD"]).returncode:
            ret = 1
        head = version(d)
        old = check_changed_versions.get_package_version(rel, base, False)
        if old and pmb.parse.version.compare(head, old) != 1:
            print(f"::error file={rel}/APKBUILD::{pkg} changed but {head} is not newer than {old}; bump pkgrel")
            ret = 1
        print(f"{pkg}: {old or '(new)'} -> {head}")
    return ret


def cmd_check_patches(everything: bool) -> int:
    heavy = os.environ.get("HEAVY") == "true"
    tier = tiers()
    pkgs = forks() if everything else changed()
    todo = [(p, d) for p, d in resolve(pkgs)
            if tier.get(p) != "heavy" or heavy or not everything]
    unavailable = [p for p, d in todo if unavailable_source(p, d)]
    if unavailable:
        return 1
    if not todo:
        print("no aports to check")
        return 0
    systemd = None
    failed = []
    for pkg, d in todo:
        if is_systemd(d) != systemd:
            systemd = is_systemd(d)
            use_systemd(systemd)
            pmbootstrap("build_init")
        a = apkbuild(d)
        deps = sorted(x for x in {*a["makedepends"], *a["makedepends_build"],
                                  *a["makedepends_host"], *a["checkdepends"]}
                      if not x.startswith("!"))
        try:
            # Copies the aport into the chroot, fetches and verifies its sources.
            pmbootstrap("checksum", "--verify", pkg)
            if deps:
                # A custom prepare() may need them; stock versions will do. A
                # dependency that only this branch provides is missing: tolerate
                # that, prepare() still fails loudly if it needed it.
                try:
                    pmbootstrap("chroot", "--", "apk", "add", "--no-interactive", *deps)
                except subprocess.CalledProcessError:
                    print(f"::warning::{pkg}: some build dependencies are not in the binary repositories")
            # abuild's own unpack and prepare: a patch that no longer applies fails here.
            pmbootstrap("chroot", "--user", "--", "sh", "-ec",
                        "cd /home/pmos/build && abuild unpack prepare && rm -rf src")
        except subprocess.CalledProcessError:
            print(f"::error::{pkg}: sources do not verify or patches do not apply ({d.relative_to(ROOT)})")
            failed.append(pkg)
    print("checked: " + ", ".join(p for p, _ in todo if p not in failed))
    return 1 if failed else 0


def read_index(data: bytes) -> dict[str, str]:
    """APKINDEX.tar.gz -> {pkgname: version}"""
    ret = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        member = tar.extractfile("APKINDEX")
        name = None
        for line in member.read().decode().splitlines() if member else []:
            if line.startswith("P:"):
                name = line[2:]
            elif line.startswith("V:") and name:
                value = line[2:]
                if name not in ret or pmb.parse.version.compare(value, ret[name]) > 0:
                    ret[name] = value
    return ret


def published() -> dict[str, str] | None:
    """Versions in this branch's published repositories, or None when an index
    could not be read (then nothing is known to be published)."""
    index_dir = os.environ.get("INDEX_DIR")
    if not index_dir:
        return None
    ret = {}
    for repo in ("pmaports", "systemd"):
        path = pathlib.Path(index_dir, repo, "APKINDEX.tar.gz")
        if path.exists():
            for name, value in read_index(path.read_bytes()).items():
                if name not in ret or pmb.parse.version.compare(value, ret[name]) > 0:
                    ret[name] = value
        elif not pathlib.Path(index_dir, repo, "NO_RELEASE").exists():
            return None
    return ret


def cmd_select() -> int:
    tier = tiers()
    heavy = os.environ.get("HEAVY") == "true"
    explicit = os.environ.get("PACKAGES", "").replace(",", " ").split()
    for pkg in explicit:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._+-]*", pkg):
            print(f"::error::not a package name: {pkg!r}")
            return 1
    for pkg in explicit:
        if aport_dir(pkg) is None or excluded(pkg):
            print(f"::error::{pkg}: no buildable aport")
            return 1
    have = published()
    if have is None:
        print("::error::Published indexes unavailable; refusing an unplanned rebuild")
        return 1
    if explicit:
        wanted = set(explicit)
        changed_now = wanted
    else:
        wanted = changed()
        changed_now = set(wanted)
        print("changed: " + (", ".join(sorted(wanted)) or "(none)"))
        if os.environ.get("FORKS") == "true":
            fork_set = forks()
            print("forked: " + ", ".join(sorted(fork_set)))
            wanted |= fork_set  # those already published are dropped below
    matrix = []
    invalid_selection = False
    for pkg, d in resolve(wanted):
        v = version(d)
        if Arch.aarch64 not in Arch.from_arch_field(apkbuild(d)["arch"]):
            print(f"{pkg}: not built for {ARCH}")
        elif tier.get(pkg) == "heavy" and not heavy:
            print(f"{pkg}: heavy tier, skipped (run the workflow manually with heavy)")
        elif tier.get(pkg) == "exclude" and not explicit:
            print(f"{pkg}: excluded in packages.conf")
        elif tier.get(pkg) == "unpublished" and pkg not in changed_now:
            print(f"{pkg}: never published (packages.conf), and not changed here")
        elif pkg in have and pmb.parse.version.compare(have[pkg], v) >= 0:
            if pkg in changed_now and not explicit:
                print(f"::error::{pkg}: changed sources do not outrank published version {have[pkg]}; bump pkgrel")
                invalid_selection = True
            else:
                print(f"{pkg}: {have[pkg]} already published; reuse it (bump pkgrel for a replacement)")
        elif unavailable_source(pkg, d):
            invalid_selection = True
        else:
            print(f"{pkg}: {v} will be built")
            matrix.append(pkg)
    if invalid_selection:
        return 1
    if len(matrix) > MAX_JOBS:
        print(f"::error::{len(matrix)} aports selected, more than the {MAX_JOBS} one run builds "
              "(GitHub caps a matrix at 256 jobs); build them in batches with the workflow's "
              "packages input")
        return 1
    (WORK / "matrix.json").write_text(json.dumps(matrix))
    return 0


def reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30):
            return True
    except (urllib.error.URLError, TimeoutError):
        return False


def use_published_repository() -> None:
    """Prebuilt first, the way a user's pmbootstrap works: forks that are
    already published satisfy build dependencies instead of being rebuilt in
    this job. Only once the repository can be read without credentials."""
    base = os.environ.get("PACKAGES_URL")
    if not base:
        return
    branch = pmb.config.pmaports.read_config_channel()["branch_pmaports"]
    found = False
    for option, mirror in (("mirrors.pmaports_custom", base), ("mirrors.systemd_custom", f"{base}/systemd")):
        if reachable(f"{mirror}/{branch}/{ARCH}/APKINDEX.tar.gz"):
            pmbootstrap("config", option, mirror)
            found = True
    if found:
        subprocess.run(["sudo", "mkdir", "-p", str(WORK / "config_apk_keys")], check=True)
        subprocess.run(["sudo", "cp", *map(str, (GITHUB / "keys").glob("*.pub")),
                        str(WORK / "config_apk_keys")], check=True)
    else:
        raise RuntimeError("published repository unavailable; refusing to rebuild dependencies unexpectedly")


def cmd_build(pkg: str) -> int:
    d = aport_dir(pkg)
    if excluded(pkg) or d is None:
        print(f"::error::{pkg}: not built here (firmware grant disabled, or no such aport)")
        return 1
    use_systemd(is_systemd(d))
    use_published_repository()
    pmbootstrap("config", "ccache_size", "1G" if pkg.startswith("linux-") else "256M")
    pmbootstrap("config", "jobs", str(min(os.cpu_count() or 1, 2)))
    pmbootstrap("build_init")
    # $WORK/config_abuild is /home/pmos/.abuild in the chroot, and abuild
    # sources that abuild.conf after /etc/abuild.conf, so this is how a
    # setting reaches every abuild run.
    conf = WORK / "config_abuild/abuild.conf"
    if PACKAGER:
        subprocess.run(["sudo", "sh", "-c", f"grep -q '^PACKAGER=' {conf} || "
                        f"echo 'PACKAGER=\"{PACKAGER}\"' >> {conf}"], check=True)
    # USE_CCACHE is abuild's, and nobody sets it: pmbootstrap only ever sets
    # CCACHE_DISABLE (when ccache is off) and Alpine's abuild.conf ships the
    # line commented out. So every build here ran without ccache, and
    # build.yml's actions/cache of cache_ccache_$ARCH cached an empty
    # directory. pmbootstrap installs ccache into every build chroot
    # (pmb.config.build_packages) and bind mounts $WORK/cache_ccache_$ARCH at
    # /home/pmos/.ccache, so turning it on is all that was missing.
    subprocess.run(["sudo", "sh", "-c", f"grep -q '^USE_CCACHE=' {conf} || "
                    f"echo 'USE_CCACHE=1' >> {conf}"], check=True)
    # --ignore-depends: build what the APKBUILD needs to build, not its runtime
    # depends. Those are aports with their own jobs, and firmware must not be
    # pulled in implicitly, even when the Taimen grant gate is enabled. Needs pmbootstrap patch 0002:
    # upstream parses -i but never applies it.
    import time
    started = time.monotonic()
    try:
        pmbootstrap("--timeout", "3600", "build", "--force", "--ignore-depends", "--arch", ARCH, pkg)
    finally:
        print(f"build elapsed seconds: {time.monotonic() - started:.1f}", flush=True)
        # Native ARM jobs use this chroot; read its cache, not a host cache.
        subprocess.run(["pmbootstrap", "stats"], check=False)
    ok = True
    for apk in sorted((WORK / "packages").glob(f"*/{ARCH}/*.apk")):
        with tarfile.open(apk) as tar:
            info = dict(line.split(" = ", 1) for line in
                        tar.extractfile(".PKGINFO").read().decode().splitlines() if " = " in line)
        if excluded(info.get("pkgname", "")) or excluded(info.get("origin", "")):
            print(f"removing {apk.name}: firmware grant not enabled")
            subprocess.run(["sudo", "rm", "-f", str(apk)], check=True)
            continue
        print(f"{apk.relative_to(WORK / 'packages')}: packager={info.get('packager')}")
        if PACKAGER and info.get("packager") != PACKAGER:
            print(f"::error::{apk.name}: packager is not the configured PACKAGER")
            ok = False
    return 0 if ok else 1


def cmd_outdated() -> int:
    channel = pmb.config.pmaports.read_config_channel()  # honours PMB_CHANNELS_CFG
    branch, alpine = channel["branch_pmaports"], channel["mirrordir_alpine"]
    sources = [f"https://mirror.postmarketos.org/postmarketos/{branch}/{ARCH}/APKINDEX.tar.gz",
               f"https://mirror.postmarketos.org/postmarketos/extra-repos/systemd/{branch}/{ARCH}/APKINDEX.tar.gz"]
    sources += [f"https://dl-cdn.alpinelinux.org/alpine/{alpine}/{repo}/{ARCH}/APKINDEX.tar.gz"
                for repo in ("main", "community") + (("testing",) if alpine == "edge" else ())]
    upstream: dict[str, list[tuple[str, str]]] = {}
    for url in sources:
        label = url.split("//", 1)[1].rsplit("/", 2)[0]
        with urllib.request.urlopen(url, timeout=60) as response:
            for name, ver in read_index(response.read()).items():
                upstream.setdefault(name, []).append((ver, label))
    missing = json.loads((GITHUB / "maintained-aports.json").read_text()).get("missing", [])
    rows = [f"| {item['name']} | missing | - | **missing maintained aport** |" for item in missing]
    outdated = len(missing)
    for pkg, d in resolve(forks()):
        ours = version(d)
        if pkg not in upstream:
            rows.append(f"| {pkg} | {ours} | - | not in upstream repositories |")
            continue
        best = upstream[pkg][0]
        for candidate in upstream[pkg]:
            if pmb.parse.version.compare(candidate[0], best[0]) == 1:
                best = candidate
        result = pmb.parse.version.compare(ours, best[0])
        status = {1: "ok", 0: "**outdated** (same version)", -1: "**outdated**"}[result]
        outdated += result != 1
        rows.append(f"| {pkg} | {ours} | {best[0]} ({best[1]}) | {status} |")
    body = ["apk installs the highest version it can see. A forked package whose",
            "version is not strictly higher than the Alpine or postmarketOS one is",
            "silently replaced by the stock build. Rebase each outdated fork onto the",
            "new upstream version, with pkgrel >= 50.", "",
            "| aport | this branch | upstream | status |", "| --- | --- | --- | --- |", *rows]
    (WORK / "outdated.md").write_text("\n".join(body) + "\n")
    (WORK / "outdated.count").write_text(str(outdated))
    print("\n".join(rows))
    return 0


def main() -> int:
    sys.argv, argv = ["pmbootstrap.py", "--aports", str(ROOT), "chroot"], sys.argv[1:]
    pmb.parse.arguments()
    get_context()
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "lint" and not rest:
        return cmd_lint()
    if cmd == "check-patches" and rest in ([], ["--all"]):
        return cmd_check_patches(rest == ["--all"])
    if cmd == "select" and not rest:
        return cmd_select()
    if cmd == "build" and len(rest) == 1:
        return cmd_build(rest[0])
    if cmd == "outdated" and not rest:
        return cmd_outdated()
    print(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main())
