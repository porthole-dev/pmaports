# Device Categorization

Devices that are working quite well get lost in the [big matrix of booting
devices](https://wiki.postmarketos.org/wiki/Devices). To improve the situation,
devices postmarketOS runs on have been grouped into the following categories.

## Categories

### Main

Requirements:
* Maintained by >= 2 people
* Working device features (where available):
  * Usable phone UI (i.e. Plasma Mobile or Phosh)
  * Calls (incl. call audio with earpiece)
  * SMS
  * Mobile Data
  * WiFi
  * Audio (speaker, main microphone ; headset, headset microphone ; jack
    detection, headset buttons)
  * Battery charging
  * Bluetooth
* Everything from community (see below)

Not required yet (shall change in the future):

* Camera

### Community

Requirements:

* Maintained by at least one person
* Well documented installation instructions on device wiki page
* Close-to-mainline kernel
* Kernel must pass `pmbootstrap kconfig check --community`, which includes
  working firewall
  ([#1119](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/issues/1119))
* Automatic kernel upgrades must work <!-- TODO: move the list below elsewhere
  and reference it to make this list shorter -->
  * When upgrading the kernel, the new kernel must be used on reboot
  * Android devices where a new `boot.img` must be flashed after upgrade need
    `deviceinfo_flash_kernel_on_update=true`.
  * For other devices which directly boot a kernel from a boot partition, or
    which use lk2nd, usually nothing needs to be done.
* Maintainer(s) must take part in the workflow for new postmarketOS releases:
  * Join the [testing
    channel](https://wiki.postmarketos.org/wiki/Matrix_and_IRC) coordinate the
    release
  * Testing their device and related fixing issues, according to the
    [timeline](https://wiki.postmarketos.org/wiki/Creating_a_release_branch#Timeline)
    (test yourself/coordinate with the
    [Testing Team](https://wiki.postmarketos.org/wiki/Testing_Team); testing
    one device per SoC is enough for community devices, but of course more is
    better)
* 2021-11 and later: track record of upgrading the kernel, device kernel or SoC
  kernel must at least have been upgraded through 3 kernel releases
* Kernel must be upgraded regularly; the kernel version used by the device may not
  be older than 6 months. The age of the kernel version is determined by the date
  the release was
  [tagged](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/refs/tags)
  upstream by Linus Torvalds or the stable kernel maintainers.
  For e.g. version 6.12.3, the date would be that of the specific patch release,
  not that of the initial 6.12 release

Regarding device features (calls working, camera, ...), there is not a fixed
feature set (so for users, don't assume that everything works, look at the
device's wiki page for details).

The purpose of community is to increase visibility of devices that:

* A lot of work was put into
* Are (and stay) working quite well (i.e. they are useful in some way and are
  tested occasionally to find and fix regressions)
* Are still being improved or are considered completed at some point

### Testing

Requirements:

* Must run a close-to-mainline kernel
* Port and dependencies build
* The device boots

### Downstream

Requirements:

* Port and dependencies build
* The device boots

Notes:

Device ports using vendor/downstream kernels. Can be moved to _testing_
once a mainline port appears. Kernels and devices in this category might be
moved to _archived_ if no longer building and either lack a maintainer or the
maintainer is unresponsive for months.

## Archived

Ports are moved to this category if:

* The port has been replaced with a better alternative (e.g. ports using
  downstream kernels when a functional mainline port exists).
* The port no longer boots with the current version of postmarketOS, and the
  port doesn't have an active maintainer to fix it.

Archived ports aren't listed in `pmbootstrap init` and binary packages are not
built for them. Still, they can be manually selected and built by entering the
device codename. A warning is displayed with the reason why they have been
archived.

This category was formerly called *unmaintained*
([!1912](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/merge_requests/1912),
[!5046](https://gitlab.postmarketos.org/postmarketOS/pmaports/-/merge_requests/5046)).

## Official Images

Official images are built by [BPO](https://build.postmarketos.org). We
configure the images as follows:

* Build images for _all_ devices in main and community
* Build images for _some_ devices in testing, maintainers may
  [enable building images](https://wiki.postmarketos.org/wiki/Bpo#Image_configuration) if:
  * The port runs a mainline kernel.
  * The port is actively maintained.
  * The maintainer has been active for some time (~6 months).

We may adjust these rules again, e.g. depending on how many testing devices will
be added over time. Testing images may be removed again, e.g. if they don't
build anymore because of device specific problems.

## Maintainers

A device maintainer must own the device and be able to test changes. They must
make sure that the device port stays in good shape.

## Moving between categories

### Moving to a higher category

Moving from testing to community, from community to main or even from testing
straight to main.

#### Request process

* Make sure that the device fulfills all requirements for the new category (see
  table above).
* Create a new merge request in which you move the files.
* Add new maintainers to the device's APKBUILD, if necessary.

#### Review process

* Everyone should be given the chance to look at the entire device port again,
  to identify issues/possible improvements. Therefore the MR should not be
  merged before a *minimum time of one week* passed. Usually, the MR should be
  in good shape when opened, and only minor fixups should need to be done
  before merging. If that is the case, then it is one week after the MR was
  opened. Otherwise, one week after there were the last significant changes.
* Reviewers should look at all files that were moved and add comments as
  necessary. (GitLab currently doesn't allow in-line comments for moved files
  ([#213446](https://gitlab.com/gitlab-org/gitlab/-/issues/213446)), so
  just add comments below the merge request.)
* Reviewers should verify that the device fulfills all requirements for the new
  category (see table above).
* Reviewers should pay special attention to consistency issues, as outlined in
  [postmarketos#24](https://gitlab.postmarketos.org/postmarketOS/postmarketos/-/issues/24).
* Consistency issues/possible improvements in the existing features (not
  missing features) should be discussed and ideally fixed before merge.
  Consistency changes that require lots of work should be documented as issues
  an expect to be fixed in the future, but should not unnecessarily delay
  merge.
* Before merging, the MR must have at least *four approvals*, 2 of which should
  be from Core Contributors.

#### After merge

* Change the category of the devices in the wiki
* When moved from testing to community:
  [enable building images](https://wiki.postmarketos.org/wiki/Bpo#Image_configuration)

### Moving to a lower category

If rules to keep a device in a category are no longer fulfilled, we should
create a merge request to move them to the now appropriate category.

## See also

* [postmarketos#25](https://gitlab.postmarketos.org/postmarketOS/postmarketos/-/issues/25) requirements for devices in main
* [postmarketos#24](https://gitlab.postmarketos.org/postmarketOS/postmarketos/-/issues/24) requirements for devices in community
* [postmarketos#16](https://gitlab.postmarketos.org/postmarketOS/postmarketos/-/issues/16)
 Increase visibility of actively maintained devices
* [postmarketos#11](https://gitlab.postmarketos.org/postmarketOS/postmarketos/issues/11#get-serious-about-supported-devices)
  Get serious about supported devices
