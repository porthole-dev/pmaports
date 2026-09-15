# Contributing

This branch carries postmarketOS packages for the porthole ports. Human-written
and AI-assisted contributions are both welcome, under the same rules.

## Commits

- **Sign off every commit** (`git commit -s`). `Signed-off-by:` is your
  [Developer Certificate of Origin](https://developercertificate.org/): it
  certifies that you have the right to submit the change. Only a person can
  give it, never an AI tool. CI rejects a pull request with a commit whose
  sign-off does not match its author.
- **Disclose AI assistance.** If an AI tool helped write a change, add an
  `Assisted-by:` trailer naming the tool (for example `Assisted-by: Claude`),
  before your sign-off. See
  [AI.md](https://github.com/porthole-dev/pmos-packages/blob/main/AI.md).
  Never list an AI tool as `Co-authored-by:` or in `Signed-off-by:`; CI
  rejects both, and tool boilerplate such as "Generated with ..." lines.
- Subjects follow pmaports: `temp/mesa: rebase onto 26.2.2`,
  `device-google-taimen: ...`.

## Packages

- A forked package keeps Alpine's or postmarketOS's `pkgver` and uses
  `pkgrel` 50 or higher, so it outranks the stock package. Bump `pkgrel` on
  every change: CI builds and publishes a version once, and the published
  repository never replaces an existing version.
- Keep the fork on the version upstream ships and carry changes as patch
  files; CI checks that the sources verify and every patch applies.
- Firmware packages (`firmware-*`) are never built or published by CI.

## What CI builds

CI never builds the whole of pmaports. It builds the packages this branch had
to fork and that have no prebuilt package yet:

- **Pull requests:** the aports the pull request changes.
- **Pushes to `taimen-bringup` and manual runs:** the aports the push changes,
  plus every *forked* aport whose exact `pkgver-pkgrel` is not in the
  published repository. An aport is forked when this branch added or changed
  it since the merge base with upstream pmaports; that set is derived from git
  on every run, so a new fork needs no list entry. Publishing then adds the
  new packages to the repository.
- A manual run can name the aports to build instead.

`.github/packages.conf` only overrides this: `heavy` aports (multi-hour
builds) are built only on a manual run with `heavy` set, `exclude` aports
are never built unless a manual run names them, and `unpublished` aports (host
tools such as `crossdirect`) are built when a change touches them but never
published.

Every published tree also carries an empty, signed `x86_64` index
(`main/x86_64`, `systemd/main/x86_64`): pmbootstrap on an x86_64 host reads the
mirror's index for its own architecture as well and aborts on a 404.

An aport whose source is downloaded from a private repository of this
organization (for example a release archive of `porthole-dev/tap`) is skipped
with a notice: abuild downloads without credentials, so it cannot be fetched
until that repository is public. Its checksums are set by the release workflow
of the app, which downloads the archive with credentials.
