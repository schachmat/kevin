"""
qemu virtual machines.
"""

import os
from pathlib import Path
import shlex
import subprocess

from . import Container, ContainerConfig


class QEMU(Container):
    """
    Represents a qemu virtual machine.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.manage = False
        self.process = None
        self.running_image = None

    @classmethod
    def config(cls, machine_id, cfgdata, cfgpath):
        cfg = ContainerConfig(machine_id, cfgdata, cfgpath)

        base_img = Path(cfgdata["base_image"])
        if base_img.is_absolute():
            base_img = cfgpath / base_img

        cfg.base_image = base_img
        cfg.overlay_image = Path(cfgdata["overlay_image"])
        cfg.command = cfgdata["command"]

        if not cfg.base_image.is_file():
            raise FileNotFoundError("base image: " + str(cfg.base_image))

        return cfg

    def prepare(self, manage=False):
        self.manage = manage

        if not self.manage:
            # create a temporary runimage

            idx = 0
            while True:
                tmpimage = Path(str(self.cfg.overlay_image) + "_%02d" % idx)
                if not tmpimage.is_file():
                    break
                idx += 1

            self.running_image = tmpimage

            command = [
                "qemu-img", "create",
                "-o", "backing_file=" + str(self.cfg.base_image),
                "-f", "qcow2",
                str(self.running_image),
            ]
            if subprocess.call(command) != 0:
                raise RuntimeError("could not create overlay image")
        else:
            # to manage, use the base image to run
            self.running_image = str(self.cfg.base_image)

    def launch(self):
        command = []
        for part in shlex.split(self.cfg.command):
            part = part.replace("IMAGENAME", str(self.running_image))
            part = part.replace("SSHPORT", str(self.ssh_port))
            command.append(part)

        self.process = subprocess.Popen(command, stdin=subprocess.PIPE)
        self.process.stdin.close()

    def is_running(self):
        if self.process:
            running = self.process.poll() is None
        else:
            running = False

        return running

    def terminate(self):
        if self.process:
            self.process.kill()
            self.process.wait()

    def cleanup(self):
        if not (self.manage or self.running_image is None):
            try:
                os.unlink(str(self.running_image))
            except FileNotFoundError:
                pass
