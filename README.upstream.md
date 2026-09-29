# pmaports (porthole-dev fork)

> **Unofficial.** Not affiliated with or endorsed by postmarketOS, Google, or
> Qualcomm. Do not report problems with this port to postmarketOS; open an
> issue here.
>
> **Experimental.** Flashing can brick the device or erase data. No warranty,
> see [LICENSE](LICENSE).
>
> **AI-assisted.** See [AI.md](AI.md).

This is an unofficial downstream fork of
[postmarketOS/pmaports](https://gitlab.postmarketos.org/postmarketOS/pmaports),
carrying the [porthole](https://github.com/porthole-dev/porthole) device ports
and the packages they need patched. See [FORK-NOTICE.md](FORK-NOTICE.md) for
what that means in practice.

Upstream's own README follows.

---

# postmarketOS aports repository

This repository contains the APKBUILD files for postmarketOS-specific packages, along with the required patches and scripts, if any.

There are many more packages defined in the [Alpine Linux aports](https://gitlab.alpinelinux.org/alpine/aports/) on which these packages depend.

Helpful resources:

* [Issues (this fork)](https://github.com/porthole-dev/pmaports/issues)
* [Issues (upstream postmarketOS)](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/work_items)
* [How to create a package](https://wiki.postmarketos.org/wiki/Create_a_package)
* [APKBUILD reference](https://wiki.alpinelinux.org/wiki/APKBUILD_Reference)
* [pmaports commit style](./COMMITSTYLE.md)
* [Approval rules](docs/merge-requests/approval-rules.md)
* [Alpine Linux aports](https://gitlab.alpinelinux.org/alpine/aports/)
* [Alpine Linux package search](https://pkgs.alpinelinux.org/packages)
* [postmarketOS package search](https://pkgs.postmarketos.org/packages)

## Git Hooks

You can find some useful git hooks in the `.githooks` directory.
To use them, run the following command after cloning this repository:

```sh
git config --local core.hooksPath .githooks
```
