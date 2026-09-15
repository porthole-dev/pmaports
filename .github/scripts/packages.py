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


def excluded(pkg: str) -> bool:
    # Vendor firmware blobs are not ours to redistribute. Hard-coded on purpose,
    # so no configuration change can publish them.
    return pkg.startswith("firmware-")


def tiers() -> dict[str, str]:
    ret = {}
    for line in (GITHUB / "packages.conf").read_text().splitlines():
        fields = line.split("#", 1)[0].split()
        if fields:
            tier, name = fields
            assert tier in ("required", "heavy"), f"packages.conf: unknown tier {tier}"
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


def changed() -> set[str]:
    if not os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA"):
        return set()
    return common.get_changed_packages(skip_archived=True)


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
            print(f"{pkg}: firmware, never built or published")
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
    if everything:
        pkgs = [p for p, t in tiers().items() if t != "heavy" or heavy]
    else:
        pkgs = changed()
    todo = resolve(pkgs)
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
                ret[name] = line[2:]
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
            ret.update(read_index(path.read_bytes()))
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
    have = published()
    if explicit:
        wanted = set(explicit)
    else:
        wanted = changed()
        if have is None:
            print("published index not readable: required packages are not added")
        else:
            wanted |= {p for p, t in tier.items() if t == "required"}
    matrix = []
    for pkg, d in resolve(wanted):
        v = version(d)
        if Arch.aarch64 not in Arch.from_arch_field(apkbuild(d)["arch"]):
            print(f"{pkg}: not built for {ARCH}")
        elif tier.get(pkg) == "heavy" and not heavy:
            print(f"{pkg}: heavy tier, skipped (run the workflow manually with heavy)")
        elif have is not None and have.get(pkg) == v:
            print(f"{pkg}: {v} already published")
        else:
            print(f"{pkg}: {v} will be built")
            matrix.append(pkg)
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
        print("published repository not readable anonymously: forked build dependencies are rebuilt here")


def cmd_build(pkg: str) -> int:
    d = aport_dir(pkg)
    if excluded(pkg) or d is None:
        print(f"::error::{pkg}: not built here (firmware, or no such aport)")
        return 1
    use_systemd(is_systemd(d))
    use_published_repository()
    pmbootstrap("build_init")
    if PACKAGER:
        conf = WORK / "config_abuild/abuild.conf"
        subprocess.run(["sudo", "sh", "-c", f"grep -q '^PACKAGER=' {conf} || "
                        f"echo 'PACKAGER=\"{PACKAGER}\"' >> {conf}"], check=True)
    # --ignore-depends: build what the APKBUILD needs to build, not its runtime
    # depends. Those are aports with their own jobs, and one of them (device ->
    # firmware) must never be built here. Needs pmbootstrap patch 0002:
    # upstream parses -i but never applies it.
    pmbootstrap("--timeout", "3600", "build", "--force", "--ignore-depends", "--arch", ARCH, pkg)
    ok = True
    for apk in sorted((WORK / "packages").glob(f"*/{ARCH}/*.apk")):
        with tarfile.open(apk) as tar:
            info = dict(line.split(" = ", 1) for line in
                        tar.extractfile(".PKGINFO").read().decode().splitlines() if " = " in line)
        if excluded(info.get("pkgname", "")) or excluded(info.get("origin", "")):
            print(f"removing {apk.name}: firmware is never published")
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
    rows, outdated = [], 0
    for pkg, d in resolve(tiers()):
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
