from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from typing import TypeAlias

from flask import Request

IPAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_trusted_proxy_cidrs(value: str | None) -> tuple[IPNetwork, ...]:
    networks: list[IPNetwork] = []
    for raw_cidr in (value or "").split(","):
        cidr = raw_cidr.strip()
        if not cidr:
            continue
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid network in UA_HOMES_TRUSTED_PROXY_CIDRS: {cidr}"
            ) from exc
    return tuple(networks)


def _parse_ip(value: str | None) -> IPAddress | None:
    candidate = (value or "").strip()
    if not candidate:
        return None
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _is_trusted(
    address: IPAddress,
    trusted_networks: Iterable[IPNetwork],
) -> bool:
    return any(
        address.version == network.version and address in network
        for network in trusted_networks
    )


def resolve_client_ip(
    remote_addr: str | None,
    forwarded_for: str | None,
    trusted_networks: tuple[IPNetwork, ...],
) -> str:
    peer = _parse_ip(remote_addr)
    if peer is None:
        return "unknown"
    if not trusted_networks or not _is_trusted(peer, trusted_networks):
        return peer.compressed

    chain: list[IPAddress] = []
    for raw_address in (forwarded_for or "").split(","):
        address = _parse_ip(raw_address)
        if address is None:
            return peer.compressed
        chain.append(address)

    for address in reversed(chain):
        if not _is_trusted(address, trusted_networks):
            return address.compressed
    return chain[0].compressed if chain else peer.compressed


def request_client_ip(
    request: Request,
    trusted_networks: tuple[IPNetwork, ...],
) -> str:
    return resolve_client_ip(
        request.remote_addr,
        request.headers.get("X-Forwarded-For"),
        trusted_networks,
    )
