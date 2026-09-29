# CI build policy

## Reuse and rebuild

Automatic runs select changed aports. Manual `forks` fills missing versions from
the maintained inventory; it does not rebuild the upstream tree. A published
version is immutable. Changed sources with the same published version fail
selection: bump `pkgrel`. HTTP failures downloading the index fail selection
instead of silently causing a large rebuild. A confirmed 404 represents a new
repository; private repositories require `PACKAGES_READ_TOKEN`.

Build dependencies use the signed binary repository where available. pmbootstrap
resolves missing build dependencies; runtime dependencies are not rebuilt by
these jobs. A library ABI change still needs explicit review and version bumps
for affected consumers: this workflow does not infer ABI compatibility.

Unavailable source repositories fail selection and patch checks. They cannot be
reported as successful skipped work; publish the reviewed source or repair the
URL before retrying.

## Compiler cache

Normal package jobs enable abuild `USE_CCACHE=1`, limit ccache to 256 MB, and
print elapsed time and chroot cache statistics. Keys contain architecture,
package and the pmbootstrap/channel inputs. Pull requests restore caches; only
successful default-branch pushes or manual builds save them. Four packages may
build concurrently.

Normal jobs no longer duplicate source archives and downloaded APKs in every
package cache. Those downloads compete with compiler objects for the repository
quota and are cheap enough to fetch again initially. Measure download time before
adding a separate bounded source cache. Chromium has its own staged checkpoints;
these are continuation state, not interchangeable with ccache.

The cap is a starting budget, not a measured optimum. Compare a cold build and
a warm build of the same revision: elapsed time, compiler hit/miss counts, cache
transfer time and archive size. Then change the budget for a demonstrated gain.
No speedup has been measured by this local cleanup.

## Chromium

The September 20 native staged run built an APK and passed five test suites.
Publication was skipped on its development branch; that proves compilation,
not delivery or behavior on a phone. Its short-lived artifact is no longer a
release source. Run the reviewed branch again and preserve the resulting APK,
source revisions, tests and checkpoint logs before enabling regular publication.

Keep scheduled builds off until a cold run and an interrupted/resumed run pass.
Use native ARM as the baseline; compare another builder using the same source,
compiler, patches and cache state. Record CPU, RAM, free disk, peak usage,
compilation time, checkpoint transfer time and actual monthly capacity. Do not
move to another forge just to obtain compute; the source host and runner can be
chosen independently.

Promotion also needs on-device launch, rendering, video and suspend testing.
Do not remove the profile's Chromium exclusion from compiler success alone.

## Retention

Publishing retains older APK versions so existing manifests remain resolvable.
It refuses different bytes under an existing filename. This is not unlimited
storage: inventory release references before pruning and archive anything still
referenced. Never delete a version merely because a newer build exists.

## pmbootstrap pin

The setup script still pins upstream plus the carried patch series. The public
pmbootstrap fork is not yet a drop-in replacement: reversing the carried code
patches against its inspected HEAD fails at `pmb/build/backend.py`. Reconcile
and run the backend tests before switching the pin; deleting the patch series
now could change Rust/crossdirect behavior. The source/patch hash is part of the
compiler-cache key, so that future transition invalidates the old cache family.
