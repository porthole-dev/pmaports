#!/usr/bin/env python3
"""PAM-free rescue channel for taimen.

WHY THIS EXISTS
    PID 1 freezing after a SIGSEGV is the worst defect on this device. When it
    happens, ping still answers and running daemons keep serving, but ssh hangs
    forever *opening a session*, because the chain is
    pam_systemd -> logind -> D-Bus -> the frozen PID 1. Every normal login path
    goes through the thing that is broken.

    So this listener deliberately touches NONE of it: no PAM, no logind, no
    D-Bus, no utmp, no new session, no pty. It accepts a line, forks
    /bin/sh -c, and writes back stdout+stderr. That is the whole design, and
    the absence of features IS the feature.

SECURITY -- READ THIS
    This is an UNAUTHENTICATED ROOT SHELL. It is therefore bound ONLY to the
    USB-gadget address, which is a physically point-to-point link to whatever
    host is holding the cable. It does NOT bind 0.0.0.0 and it will EXIT rather
    than fall back to a wildcard bind, so it can never be reachable over WiFi
    or the modem. Do not "fix" that by binding wider.

USAGE
    host$ nc 172.16.42.1 2323
    then one shell command per line. `exit` closes the connection.
"""

import socket
import socketserver
import subprocess

BIND_ADDR = "172.16.42.1"  # USB gadget only. Never 0.0.0.0. See SECURITY above.
BIND_PORT = 2323
TIMEOUT = 30  # per-command, so a hung command cannot wedge the rescue channel too


class RescueHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"taimen rescue (PAM-free). one command per line, 'exit' to quit.\n")
        for raw in self.rfile:
            cmd = raw.decode("utf-8", "replace").strip()
            if not cmd:
                continue
            if cmd in ("exit", "quit"):
                return
            try:
                out = subprocess.run(
                    ["/bin/sh", "-c", cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=TIMEOUT,
                ).stdout
            except subprocess.TimeoutExpired:
                out = b"<rescue: timed out after %ds>\n" % TIMEOUT
            except Exception as exc:  # never let one bad command kill the channel
                out = f"<rescue: {exc}>\n".encode()
            self.wfile.write(out)
            self.wfile.flush()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    address_family = socket.AF_INET


if __name__ == "__main__":
    # Bind explicitly; if the gadget address is not up yet the unit restarts.
    # Exiting is correct here -- a wildcard fallback would expose a root shell.
    with Server((BIND_ADDR, BIND_PORT), RescueHandler) as srv:
        srv.serve_forever()
