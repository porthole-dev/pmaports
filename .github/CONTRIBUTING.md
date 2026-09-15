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
- List long-lived forks in `.github/packages.conf` (`required`, or `heavy` for
  multi-hour builds).
- Firmware packages (`firmware-*`) are never built or published by CI.
