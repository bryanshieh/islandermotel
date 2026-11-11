"""Run the app so a phone or tablet on the same network can use it.

`runserver` only answers the laptop itself. This command listens on the
network, turns DEBUG off, and prints the address to type into the phone.
"""

import os
import socket
import subprocess
import sys

from django.core.management.base import BaseCommand

# Tailscale's MagicDNS names all end in .ts.net.
TAILSCALE_SUFFIX = ".ts.net"


def lan_addresses():
    """This computer's IPv4 addresses on the local network."""
    found = set()
    try:
        # No data is sent; this only asks the OS which address it would use.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(address for address in found if not address.startswith("127."))


def allowed_hosts(addresses, extra_hosts):
    return list(addresses) + [TAILSCALE_SUFFIX] + list(extra_hosts)


class Command(BaseCommand):
    help = "Serve the app to phones and tablets on the same network (or over Tailscale)."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=8000)
        parser.add_argument(
            "--host",
            action="append",
            default=[],
            help="Extra name or address to accept, e.g. a Tailscale 100.x.y.z address. Repeatable.",
        )

    def handle(self, *args, **options):
        port = options["port"]
        addresses = lan_addresses()
        hosts = allowed_hosts(addresses, options["host"])

        self.stdout.write(self.style.SUCCESS("Islander Motel audits is running."))
        self.stdout.write("On this laptop:   " f"http://127.0.0.1:{port}/")
        if addresses:
            for address in addresses:
                self.stdout.write(f"On your phone:    http://{address}:{port}/   (same wifi)")
        else:
            self.stdout.write("No network address found. Is the laptop connected to wifi?")
        for host in options["host"]:
            self.stdout.write(f"Also accepting:   http://{host}:{port}/")
        self.stdout.write(f"Over Tailscale:   http://<laptop-name>.<tailnet>{TAILSCALE_SUFFIX}:{port}/")
        self.stdout.write("Keep this window open. Press Ctrl+C to stop.\n")

        env = {
            **os.environ,
            "DJANGO_DEBUG": "0",
            "DJANGO_ALLOWED_HOSTS": ",".join(hosts),
        }
        try:
            subprocess.run(
                [sys.executable, "-m", "waitress", f"--listen=0.0.0.0:{port}", "config.wsgi:application"],
                env=env,
                check=False,
            )
        except KeyboardInterrupt:
            self.stdout.write("\nStopped.")
