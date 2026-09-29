# Pixel 2 XL experimental Nura image

Target: Google Pixel 2 XL (taimen), mainline Linux, Phosh, systemd.
Includes the licensed nonfree firmware. This candidate has passed build checks;
hardware testing applies only when a report names this exact image checksum.

## Verify and unpack

Download every asset into one directory, then run:

```sh
sha256sum -c SHA256SUMS
gzip -dk google-taimen.img.gz
```

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
