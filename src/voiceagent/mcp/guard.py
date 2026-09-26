"""Where an MCP server may live.

The backend runs with a public URL and a network that also reaches internal
services — Render's private network, the database, a cloud metadata endpoint.
A server URL is typed in by whoever holds the console, and the backend then
connects to it and relays what comes back, so an unchecked URL is a way to
make the server fetch from inside its own network (SSRF). This refuses
anything that is not a public address.

The check resolves the host and inspects every address it resolves to: a
public hostname with one private record is still a way in. It runs again each
time a connection is opened, not only when the server is added, so a DNS
record repointed after the fact is refused too. MCP transports only follow
redirects within the endpoint's origin, so a redirect cannot route around it.

`MCP_ALLOW_PRIVATE_HOSTS=true` lifts both rules — https only, public only —
for local development against a server on your own machine. Read when used,
so it can be flipped without a restart.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

BUILTIN_SCHEME = "builtin"


class UnsafeUrl(ValueError):
    """The URL points somewhere a server must not connect to. Says why."""


def private_hosts_allowed() -> bool:
    return os.getenv("MCP_ALLOW_PRIVATE_HOSTS", "").strip().lower() in {"1", "true", "yes", "on"}


def check_url(url: str) -> None:
    """Raise `UnsafeUrl` unless `url` is a server this backend may connect to."""
    parts = urlsplit(url.strip())
    if parts.scheme == BUILTIN_SCHEME:
        return  # in-process, never touches the network

    allow_private = private_hosts_allowed()
    schemes = {"https", "http"} if allow_private else {"https"}
    if parts.scheme not in schemes:
        reason = " Plain http would send your credentials unencrypted." if parts.scheme == "http" else ""
        raise UnsafeUrl(f"The URL must start with https://.{reason}")
    host = parts.hostname
    if not host:
        raise UnsafeUrl("The URL has no host name.")
    if allow_private:
        return

    for address in _resolve(host, parts.port or 443):
        if not _is_public(address):
            raise UnsafeUrl(
                f"{host} points to a private or reserved network address ({address}). "
                "Only servers on the public internet can be connected."
            )


def _resolve(host: str, port: int) -> set[str]:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        pass
    else:
        return {host}  # already an address; nothing to look up

    try:
        # Looked up on the module at call time, not imported by name, so a
        # test can stand in for DNS.
        records = socket.getaddrinfo(host, port)
    except (socket.gaierror, UnicodeError) as exc:
        # Refused rather than waved through: an address we cannot see is one
        # we cannot vouch for.
        raise UnsafeUrl(f"Could not find {host}. Check the URL.") from exc
    addresses = {record[4][0] for record in records}
    if not addresses:
        raise UnsafeUrl(f"Could not find {host}. Check the URL.")
    return addresses


def _is_public(address: str) -> bool:
    # A scope id ("fe80::1%eth0") is not part of the address.
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped  # ::ffff:10.0.0.1 is 10.0.0.1
    return not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        # Catches what the flags above leave out, such as carrier-grade NAT
        # (100.64.0.0/10), which cloud providers use internally.
        or not ip.is_global
    )
