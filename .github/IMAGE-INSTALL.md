# Pixel 2 XL experimental Nura image

Target: Google Pixel 2 XL (taimen), mainline Linux, Phosh, systemd.
Includes the licensed nonfree firmware. This candidate has passed build checks;
hardware testing applies only when a report names this exact image checksum.

## Recommended: one download, one command

Download `google-taimen-install.zip` and install Python 3.8 or newer and current
Android platform-tools. Back up all data and unlock the bootloader using the
device guide. Connect exactly one Pixel 2 XL in bootloader mode, then run:

```sh
python3 google-taimen-install.zip
```

The bundle verifies every included asset, checks the phone model and unlocked
bootloader, asks for explicit confirmation, then flashes userdata, matching boot
and DTBO to the reviewed slot b and reboots. It stops on a failed write. Keep
about 8 GiB free for temporary image extraction. Windows: use `py -3` instead of
`python3`; pass `--fastboot /path/to/fastboot` if fastboot is not on PATH.

Use `--dry-run` to verify and preview without contacting a phone. Verify the ZIP's
published checksum (`BUNDLE-SHA256SUMS`) and GitHub provenance before running it:

```sh
gh attestation verify google-taimen-install.zip -R porthole-dev/pmaports
```

Separate images remain available for experienced users and recovery.

## Manual alternative: verify and unpack

Download the separate installation assets. Verify each against `SHA256SUMS`,
then decompress `google-taimen.img.gz` with `gzip -dk google-taimen.img.gz`.
The checksum file covers release metadata as well; `sha256sum -c SHA256SUMS`
requires every listed file.

The default account is `user`. The initial password is selected by the maintainer
through the release environment. Change it after installation.

## Full installation

Flashing replaces the installed operating system and user data. Back up first.
The bootloader must be unlocked. Use a current Android platform-tools fastboot.
These instructions target the port's tested slot b. Never activate slot a.

From the bootloader, verify that fastboot identifies your Pixel 2 XL before
performing these writes:

```sh
fastboot devices
fastboot flash userdata google-taimen.img
fastboot flash boot_b boot.img
fastboot flash dtbo_b dtbo.img
fastboot set_active b
fastboot reboot
```

The DTBO write is required: the stock overlay does not match the mainline kernel.
Keep `boot.img`, `dtbo.img`, and the rootfs from the same release together.

Support, limitations, and dated hardware reports:
https://porthole-dev.github.io/porthole/devices/google-taimen/
