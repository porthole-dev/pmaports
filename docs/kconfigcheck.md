# kconfigcheck

postmarketOS defines a set of kernel configuration options that should be
enabled in all kernel packages.

These are for example options required for the initramfs or our firewall to
function, but also include required options for commonly used software
such as Docker or podman. Additionally, we enable drivers for hardware that
could be plugged into a device. Others reflect our distribution policy, e.g.
security or hardening-related configs.

These configuration options are listed in the `kconfigcheck.toml` file in
pmaports and grouped into categories. Options can be required conditionally by
matching on kernel version range and architecture.

```toml
["category:virt".">=0.0.0"."all"]
HW_RANDOM_VIRTIO = "m"
KVM = "y"
VIRTUALIZATION = "y"
```

This example above would require three config options to be enabled for all
kernel versions and all architectures. `HW_RANDOM_VIRTIO` is preferred as a
module, but enabling it as built-in would still pass the configuration checks.

Aliases can be defined for grouping multiple categories together:

```toml
[aliases]
my-alias = ["category:one", "category:two"]
```

In this case, the `my-alias` alias would include all requirements from the
categories `one` and `two`.

## Enabling the config checks

Kernel packages in pmaports can opt into more strict kconfig checks by adding
them in the `options` in their `APKBUILD`:

```
options="pmb:kconfigcheck-community"
```

This would opt into the `community` category checks. The checks can be
performed by running `pmbootstrap kconfig check [kernel-package-name]`.
The `community` category checks are mandatory for devices in the community
and main categories, see the
[device categorization requirements](./device-categorization) for more
information.

## Changing the requirements

Changes to `kconfigcheck.toml`, like requiring new options, removing
requirements or changing options from built-in to module or vice-versa, can be
done in a merge request to pmaports. Changing the requirements does not require
updating all kernels to be compliant - this is the responsibility of the kernel
package maintainers, who must make sure their kernel complies with the changed
requirements in the next update to their kernel packages. When making unrelated
changes to a kernel package that does not meet the current requirements, one
can use the `[ci:skip-kconfigcheck]` CI tag to bypass the checks if
[the situation allows for it](./ci-tags).

Merge requests that change the `kconfigcheck.toml` require approval from
members of the kconfigcheck team in GitLab. The team can be pinged on merge
requests via `@teams/kconfigcheck`. Trivial changes that are not expected to
break any usecases and don't conflict with our policies can be merged with
approval of one team member. Any other, nontrivial changes require approval of
all team members.

