#!/usr/bin/env python3
"""Boot/install/reboot an ISO with no NIC, using only a new disposable VM disk.

Requires a host-native qemu-system-x86_64 and its share/qemu firmware directory.
Never accepts a host disk path. Temporary images/logs stay in --work-dir.
"""
import argparse
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import subprocess
import time


class Console:
    def __init__(self, command, log):
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.log = log.open('wb')
        self.buffer = ''

    def expect(self, pattern, timeout=600):
        deadline = time.monotonic() + timeout
        expression = re.compile(pattern)
        while time.monotonic() < deadline:
            match = expression.search(self.buffer)
            if match:
                self.buffer = self.buffer[match.end():]
                return match
            if self.proc.poll() is not None:
                raise RuntimeError(f'QEMU exited {self.proc.returncode}: {self.buffer[-1500:]}')
            if select.select([self.proc.stdout], [], [], 1)[0]:
                data = os.read(self.proc.stdout.fileno(), 65536)
                self.log.write(data)
                self.log.flush()
                self.buffer += data.decode(errors='replace')
        raise TimeoutError(f'Waiting for {pattern}: {self.buffer[-1500:]}')

    def send(self, value):
        self.proc.stdin.write((value + '\n').encode())
        self.proc.stdin.flush()

    def command(self, command, expected=0, timeout=600):
        # printf format keeps the complete marker out of the echoed input line.
        self.send(command + "; crt_status=$?; printf '\\nCRT_%s:%s\\n' RESULT \"$crt_status\"")
        match = self.expect(r'CRT_RESULT:(\d+)', timeout)
        assert int(match.group(1)) == expected, (command, match.group(1))
        self.expect(r'(?:nixos@ground-station-installer|ground-admin@ground-station)[^\n]*\$')

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--iso', type=Path, required=True)
    parser.add_argument('--firmware-dir', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--resume-install', action='store_true',
                        help='Reuse this test directory after its installation stage completed')
    parser.add_argument('--boot-installed', action='store_true',
                        help='Only cold-boot the installed disk from this test directory')
    args = parser.parse_args()
    work = args.work_dir.resolve()
    disk = work / 'disposable.qcow2'
    variables = work / 'efi-vars.fd'
    if args.resume_install or args.boot_installed:
        assert disk.is_file() and not disk.is_symlink() and variables.is_file()
    else:
        work.mkdir(parents=True, exist_ok=False)
        subprocess.run([str(args.qemu.with_name('qemu-img')), 'create', '-f', 'qcow2',
                        str(disk), '16G'], check=True)
        shutil.copyfile(args.firmware_dir / 'edk2-i386-vars.fd', variables)
    common = [str(args.qemu), '-machine', 'q35', '-accel', 'tcg', '-m', '3072',
              '-smp', '2', '-nic', 'none', '-display', 'none', '-serial', 'stdio',
              '-no-reboot', '-drive',
              f'if=pflash,format=raw,readonly=on,file={args.firmware_dir / "edk2-x86_64-code.fd"}',
              '-drive', f'if=pflash,format=raw,file={variables}',
              '-drive', f'if=none,id=station-disk,format=qcow2,file={disk}',
              '-device', 'nvme,drive=station-disk,serial=CRT-GROUND-VM']
    # Disposable console-only test password; never used on any real machine.
    password = 'Disposable-VM-only-9274'
    if not args.boot_installed:
        installer_common = common
        if args.resume_install:
            # Preserve the installed NVRAM boot entry for the final disk-only boot;
            # fresh live-media variables ensure recovery boots the CD first.
            live_variables = work / 'live-resume-vars.fd'
            shutil.copyfile(args.firmware_dir / 'edk2-i386-vars.fd', live_variables)
            installer_common = [arg.replace(f'file={variables}', f'file={live_variables}') for arg in common]
        vm = Console(installer_common + ['-cdrom', str(args.iso.resolve()), '-boot', 'order=d'],
                     work / 'installer-console.log')
        try:
            vm.expect(r'nixos@ground-station-installer[^\n]*\$')
            print('PASS: UEFI installer booted with no network adapter', flush=True)
            vm.command('test -d /sys/firmware/efi && test "$(ls /sys/class/net)" = lo')
            vm.command('! systemctl is-active --quiet sshd')
            if args.resume_install:
                vm.command('sudo mount -t ext4 /dev/nvme0n1p2 /mnt && sudo mount -t vfat /dev/nvme0n1p1 /mnt/boot')
            else:
                vm.command('sudo crt-install-um560 --check', expected=1)
                vm.command('test ! -e /dev/nvme0n1p1')
                vm.command("sudo sh -c " + shlex.quote('''set -eu
        parted --script /dev/nvme0n1 mklabel gpt mkpart ESP fat32 1MiB 1025MiB set 1 esp on mkpart root ext4 1025MiB 100%
        udevadm settle
        mkfs.fat -F 32 -n CRT-GS-EFI /dev/nvme0n1p1
        mkfs.ext4 -L CRT-GS-ROOT /dev/nvme0n1p2
        mount -t ext4 /dev/nvme0n1p2 /mnt
        mkdir -p /mnt/boot
        mount -t vfat /dev/nvme0n1p1 /mnt/boot
        '''))
                vm.command('sudo crt-install-um560 --check')
                vm.send('sudo crt-install-um560 --install')
                vm.expect(r'New password:', timeout=1200)
                vm.send(password)
                vm.expect(r'Retype new password:')
                vm.send(password)
                vm.expect(r'Installed\. Reboot and remove the installer USB\.')
                vm.expect(r'nixos@ground-station-installer[^\n]*\$')
            vm.command('test -e /mnt/nix/var/nix/profiles/system/kernel && test -e /mnt/boot/EFI/BOOT/BOOTX64.EFI')
            # Serial visibility is VM instrumentation only, not an assumed UM560 UART.
            vm.command('sudo sh -c ' + shlex.quote("sed -i '/^options /s/$/ console=ttyS0,115200/' /mnt/boot/loader/entries/nixos*.conf"))
            vm.command('sudo umount -R /mnt')
            vm.command('sync')
            print('PASS: embedded closure installed offline; bootloader and local account configured', flush=True)
        finally:
            vm.close()
    # No CD attached; same firmware variables and disk, still no NIC.
    vm = Console(common + ['-boot', 'order=c'], work / 'installed-console.log')
    try:
        vm.expect(r'ground-station login:', timeout=600)
        vm.send('ground-admin')
        vm.expect(r'Password:')
        vm.send(password)
        vm.expect(r'ground-admin@ground-station[^\n]*\$')
        vm.command('systemctl is-active nginx sshd')
        vm.command('curl --fail http://127.0.0.1:8080/healthz')
        vm.command('test "$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/readyz)" = 503')
        vm.command('test "$(findmnt -n -o LABEL /)" = CRT-GS-ROOT && test "$(findmnt -n -o LABEL /boot)" = CRT-GS-EFI')
        vm.command('test "$(ls /sys/class/net)" = lo')
        print('PASS: installed system cold-booted without ISO/network; console, SSH service, UI and mounts verified', flush=True)
    finally:
        vm.close()
    (work / 'PASS').write_text('UEFI ISO boot, offline install and installed cold boot passed\n')


if __name__ == '__main__':
    main()
