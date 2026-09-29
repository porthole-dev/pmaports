# Nura device packages

[Website](https://porthole-dev.github.io/porthole/) · [Downloads](https://porthole-dev.github.io/porthole/downloads/) · [Device support](https://porthole-dev.github.io/porthole/devices/)

Downstream Nura packages for the porthole Taimen port. Upstream still calls its
packaging project postmarketOS/pmaports; those Git and package interfaces stay
unchanged. Upstream project documentation is preserved in
[README.upstream.md](README.upstream.md).

## What belongs here

Device packages, kernel patch series and the userspace forks needed by our
profiles. [Maintained aports](.github/maintained-aports.json) records ownership
and purpose. It is generated from porthole's profile and shared manifests.
Do not infer maintained packages from the Git merge base: this fork contains
rewritten history.

## Build and check

Use [porthole](https://github.com/porthole-dev/porthole) and its rootless
workspace for local builds. CI runs the same pmbootstrap entry point through
[run-pmbootstrap.sh](.github/scripts/run-pmbootstrap.sh).

- Pull requests: commit policy, APKBUILD/version checks, source/patch checks,
  and changed non-heavy packages.
- Manual Build: select named packages or fill missing maintained packages.
  Heavy packages require explicit opt-in.
- Upstream check: compare maintained package versions against binary indexes.
  A newer or equal upstream version requires review.
- Chromium: staged build and checkpoint workflow; see [build policy](BUILDING.md).

Signed packages are distributed through
[pmos-packages](https://github.com/porthole-dev/pmos-packages).
Device images and hardware support are tracked in
[Porthole](https://github.com/porthole-dev/porthole).
A successful package build alone does not establish hardware support.

## Before submitting

Bump `pkgrel` whenever packaged contents change. Keep source URLs public,
checksums current and patches attributable. Taimen firmware is published under the recorded Google and Qualcomm grant; other firmware is excluded.
Read [the contribution policy](https://github.com/porthole-dev/.github/blob/main/CONTRIBUTING.md).
