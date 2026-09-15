# Building chromium on GitHub Actions

`temp/chromium` takes far longer to build than GitHub's 6 hour job limit,
even on the fastest hosted runner. `build.yml` therefore keeps it in the
`heavy` tier and never builds it. `workflows/chromium.yml` builds it in
stages that resume one another, and publishes it with the same signed
`publish-repo.sh` path that `build.yml` uses.

## How to use it

- **Actions → Chromium → Run workflow** on `taimen-bringup`. The defaults
  build natively on arm64 with up to 10 build jobs, then publish.
- **Running it again continues the build.** A run that ends before ninja has
  finished leaves its state stored. The next run of the same aport picks it
  up, whether the earlier run ran out of build jobs, failed, or was
  cancelled.
- **Test the mechanism cheaply:** `stages=2`, `stage_minutes=20`,
  `publish=false`.
- **Schedule:** the daily cron does nothing unless the repository variable
  `CHROMIUM_SCHEDULE` is `true`. When it is enabled, it builds the aport if
  that exact version is not published yet, and resumes an unfinished build.

## The design

```
plan ─ prep ─ build 1 ─ build 2 ─ … ─ build 10 ─ package ─ publish
```

| job | runs | stores |
| --- | --- | --- |
| plan | computes the state tag. Stops if this `pkgver-pkgrel` is already published. Prunes states idle for 14 days. | nothing |
| prep | `packages.py build chromium`, exactly what `build.yml` runs. Stopped by the watchdog when ninja starts. | the prep layer: the whole pmbootstrap work directory (chroots, prepared source tree, `gn gen` output) |
| build k | restore, then abuild's `build` part until the deadline | `out/bld` as the newest out layer, and the manifest |
| package | restore, then abuild's `build check rootpkg` parts | the apks, as the `packages-chromium` artifact |
| publish | `publish-repo.sh`, then verifies the published index the way `build.yml` does, then deletes the state | the release assets in `pmos-packages` |

### The same apk pmbootstrap builds

Nothing here runs a second build recipe. prep is `build.yml`'s own build
step. The later jobs re-enter the same work directory through pmbootstrap's
API: `pmb.chroot.init`, `configure_abuild`, the sysroot bind mount, and
`mount_pmaports`. They run abuild with pmbootstrap's own
`pmb.build.backend.abuild_env()`. The parts they run are the rest of abuild's
own sequence for `all`:

```
validate builddeps clean fetch unpack prepare mkusers | build | build | … | build check rootpkg
                prep                                   build 1  build 2    package
```

The runner arch decides the path, as pmbootstrap always does. On arm64
(the default) pmbootstrap builds natively, which is Alpine's path. On
x86_64 it builds with `pmb:cross-native2` and the unbundled cross
toolchains from `cross-unbundle-toolchains.patch`. The APKBUILD has no CI
special case.

### Resume, and why it can be trusted

- **Time-boxing:**
  - The deadline is measured from the start of the job (`START`): ninja
    stops 45 minutes before the 6 hour limit, or after `stage_minutes`,
    whichever comes first.
  - A watchdog thread in `scripts/chromium-stage.py` sends SIGTERM to ninja
    only, and never to pmbootstrap or abuild, so they fail cleanly.
  - samurai (Alpine's ninja) passes the signal on to its jobs and exits.
  - An interrupted job writes no `.ninja_log` record. samurai treats an
    output with no record as dirty ("no record in .ninja_log", `isdirty()`
    in samurai's `build.c`), so a partly written object is rebuilt, never
    trusted.
  - Whether a stage was stopped deliberately is decided by the watchdog
    itself, not by guessing from exit codes.
- **mtimes:** tar's `posix` format keeps mtimes to the nanosecond, the
  resolution samurai compares.
- **A frozen toolchain:**
  - Alpine edge changes daily. Every stage restores the chroots that prep
    installed, so all objects are compiled by one clang against one set of
    headers.
  - This matters because Chromium's depfiles (`-MMD`) do not list system
    headers, so ninja would not notice a newer header.
- **Integrity between stages:**
  - Every part carries a sha256 in the manifest, and a part is checked
    before it is unpacked. zstd frame checksums add a second check.
  - After a restore, the number of ninja log records must equal the number
    the manifest recorded, or the job fails before it builds anything.
  - While ninja runs, the watchdog counts outputs that earlier stages had
    already recorded and that are now being rebuilt. More than 1000 means
    the restore is inconsistent (lost mtimes, a changed command line), so it
    stops the stage within a minute instead of burning 5 hours.
- **Atomic commit:** parts are uploaded first and `state.json` last. The
  previous out layer is deleted only after the new manifest is up. A job
  that dies while uploading leaves the previous state intact.
- **Failure semantics:** a stage that fails for any reason other than its
  deadline (a compile error, OOM) still stores its progress. samurai's log
  is consistent after a failure too. The job then fails and the chain
  stops. **Re-run failed jobs**, or a new run, resumes from that progress.
  A failure never restarts the build.

### Where state lives

- **Draft releases of this repository**, tagged
  `chromium-state-<pkgver>-r<pkgrel>-on-<arch>-<key>`.
- **The key** hashes:
  - a format version
  - the runner
  - the git tree of `temp/chromium`
  - `.github/pmbootstrap-patches`
  - `run-pmbootstrap.sh`

  A change to any of these gets a new state. The old one is pruned after 14
  idle days, or deleted by publish.
- **Why not the alternatives:**
  - The actions cache is 10 GB per repository, evicts least recently used
    entries, and is shared with `build.yml`'s apk and ccache caches.
  - Artifacts count against the private repository's storage quota and
    expire with their run.
  - Release assets have no total size limit, only 2 GiB per file, so layers
    are split into 1900 MiB parts.
  - Drafts are visible only to people with write access, even once the
    repository is public.

## Compared with other Chromium forks' CI

All of these time-box ninja, tar the tree, and pass it to the next job:

- [ungoogled-chromium-portablelinux](https://github.com/ungoogled-software/ungoogled-chromium-portablelinux/blob/master/.github/workflows/build-steps.yml)
  and [Helium](https://github.com/imputnet/helium-linux/blob/main/.github/workflows/build-steps.yml)
  run 10 parts of `timeout 5h ninja` and pass the whole `build/` tree as one
  artifact.
- [ungoogled-chromium-windows](https://github.com/ungoogled-software/ungoogled-chromium-windows/blob/master/.github/workflows/reusable-build.yml)
  runs 16 stages.
- [ungoogled-chromium-archlinux](https://github.com/ungoogled-software/ungoogled-chromium-archlinux/blob/master/.github/workflows/release.yml)
  and [-macos](https://github.com/ungoogled-software/ungoogled-chromium-macos/blob/master/.github/scripts/github_build.sh)
  are the only ones that checksum the archive, and macOS derives the
  timeout from the job's start.
- [jclaveau/ci-prebuilds](https://github.com/jclaveau/ci-prebuilds/blob/main/playwright/alpine-browsers/chromium-headless-shell/scripts/ninja-resume.sh)
  builds Alpine's musl Chromium in Docker image layers. Its notes record
  that busybox `timeout` never returns 124, and that sccache over the GHA
  cache got 1.33% hits.

What this workflow does differently:

1. **The state is keyed by content and lives outside any one run.** The
   others lose everything when an artifact expires or a run ends. Here a
   new run resumes whatever an earlier run of the same aport left.
2. **Prepared sources are uploaded once.** The others re-upload the full
   tree (sources and all) after every part. Here each build job uploads
   only `out/bld`.
3. **Integrity and progress are checked.** Parts carry sha256 sums, the
   restored ninja log is counted, and the watchdog catches a restore that
   has started rebuilding everything. None of the ninja-based chains above
   notices a restore that silently rebuilds everything.
4. **A failure resumes.** Progress is stored on failure too. The others
   store only after a clean timeout.
5. **The toolchain is frozen** in the state, not re-installed per stage from
   a moving distribution.
6. **The package is pmbootstrap's.** The build is not a bespoke `gn`/`ninja`
   invocation: prep is `build.yml`'s build, and the rest is abuild's own
   parts with pmbootstrap's environment.
7. **No compiler cache for a cold build.** The out directory is the cache.
   ci-prebuilds' measurement shows why a GHA-backed sccache does not help.

## Native arm64 or x86_64 cross

`ubuntu-24.04-arm` is the default. Once the repositories are public, both
runner types have 4 vCPUs and 16 GB of RAM
([runner specs](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)).
Two reasons favour arm64:

- **Physical cores.** The arm64 runners are Cobalt 100 VMs, which give "an
  entire physical core for each virtual machine vCPU"
  ([Dpsv6](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dpsv6-series)).
- **Less to build.** A cross build compiles more: the host toolchain, and the
  V8 snapshot toolchain. The context snapshot generator links Blink, so
  Blink and V8 are compiled twice. See "Measured" for the ninja edge counts.

The x86_64 cross path stays available (`runner: ubuntu-24.04`). It is the
fast path on an x86_64 workstation.

## Measured

On a **private-repository `ubuntu-24.04-arm` runner (2 vCPU, 8 GB)**, run
[35033564900](https://github.com/porthole-dev/pmaports/actions/runs/35033564900):

| step | time |
| --- | --- |
| disk after cleanup | 36 GB free -> 54 GB free, in 1 min |
| build the forked mesa (only while `pmos-packages` cannot be read anonymously) | 28.7 min |
| install chromium's build dependencies | 0.4 min |
| download and unpack the 1.7 GB source tarball | 1.6 min |
| `prepare`: copium and the aport's patches, unbundling | 2.2 min |
| `gn gen` ("Done. Made 31446 targets from 4917 files") | 0.6 min |
| tar + zstd -3 + upload of the prep layer | 5.4 min |
| **prep layer stored** | **2.92 GB in 2 parts** (13 GB of work directory) |

`.github/scripts/chromium-state-test.sh` runs the layering (prep, two stages,
restore, a corrupted part) against a fake `gh` in about a second.

**Not yet measured on real runners:** the build and package jobs. The
organization ran out of included Actions minutes for private repositories
during this work ("The job was not started because recent account payments
have failed or your spending limit needs to be increased"), so nothing has
run since the prep layer was stored. The stored state is keyed by the aport's
git tree, so the next run picks it up and starts with build job 1.

## Cost and wall-clock once public

Public repositories get free minutes and 4 vCPU runners, so the numbers below
are for that. They are estimates; the build jobs have not run yet.

- **Reference point:** [ci-prebuilds](https://github.com/jclaveau/ci-prebuilds/blob/main/.agents/auto-memory/project_chromium_from_source_split_build.md)
  measured a cold Alpine musl Chromium (headless shell, ~37000 ninja actions)
  at about 13 h on a 4 vCPU x64 runner.
- This package builds `chrome`, `headless_shell`, `chromedriver`,
  `chrome_crashpad_handler` and, natively, five unit test binaries, so expect
  more actions than that.
- **Native arm64:** 4 physical cores, so roughly **15-20 h of ninja**: 4 build
  jobs of 5 h, plus prep (~10 min once mesa is published), plus package
  (`check` runs Alpine's unit tests), plus ~10 min per job of restore and
  store. Call it **17-23 h of runner time** for a cold build, spread over one
  or two runs of the chain.
- **x86_64 cross:** more work (the host toolchain, and Blink and V8 again for
  the V8 context snapshot generator) on 4 vCPUs that are SMT threads: expect
  roughly half the throughput, 7 or more build jobs.
- **Storage:** one state is the prep layer (~3 GB) plus the newest out layer
  (expect 5-10 GB). Release assets do not count against the Actions storage
  quota, and the state is deleted when the package is published.
- **A rebuild for a new Chromium version starts cold.** Nothing is shared
  between versions today; see "Possible improvements".

## Possible improvements

- **A ccache layer across versions.** A security bump (152.0.7977.82 ->
  .95) changes few translation units. `USE_CCACHE=1` and a stored ccache
  layer would turn a 17 h rebuild into a few hours. It costs another layer to
  store and restore, and only pays off from the second version on.
- **Incremental out layers.** Each build job stores the whole out directory.
  Storing only what changed would cut the upload, but restoring then needs
  every layer, and files deleted by build actions would have to be tracked.
- **Extracting build.yml's publish step into a script** that both workflows
  call. Right now chromium.yml repeats it (it calls the same
  `publish-repo.sh`, but the release glue around it is duplicated).

## Cleanup

- The publish job deletes the state it published.
- `plan` deletes any other `chromium-state-*` draft whose manifest has not
  changed for 14 days.
- To delete one by hand: `bash .github/scripts/chromium-state.sh delete <tag>`
  with `GH_TOKEN` and `GITHUB_REPOSITORY` set, or delete the draft release in
  the web UI.
- Nothing else is stored: the `packages-chromium` artifact expires after 7
  days.
