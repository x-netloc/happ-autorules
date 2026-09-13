#!/usr/bin/env python3
"""Build Happ routing profiles and deeplinks from autorules."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tomllib
from pathlib import Path
from typing import Any


ACTION_FIELDS = {
    "direct": ("DirectSites", "DirectIp"),
    "proxy": ("ProxySites", "ProxyIp"),
    "reject": ("BlockSites", "BlockIp"),
}
ACTION_ORDER_NAMES = {
    "direct": "direct",
    "proxy": "proxy",
    "reject": "block",
}
SELECTORS = {"geosite", "geoip", "domains", "cidrs"}


class BuildError(Exception):
    pass


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BuildError(f"cannot read {path}: {exc}") from exc


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def validate_category_files(
    categories: dict[str, list[str]],
    geosite_dir: Path,
    geoip_dir: Path,
) -> None:
    missing: list[str] = []
    for category in categories["geosite"]:
        path = geosite_dir / f"geosite_{category}.txt"
        if not path.is_file():
            missing.append(f"geosite:{category}")
    for category in categories["geoip"]:
        path = geoip_dir / f"geoip_{category}.txt"
        if not path.is_file():
            missing.append(f"geoip:{category}")
    if missing:
        raise BuildError(f"categories missing from upstream DAT: {', '.join(missing)}")


def happ_route_order(profile: dict[str, Any]) -> str:
    seen: list[str] = []
    for rule in profile["rules"]:
        action = rule["action"]
        if action not in ACTION_FIELDS:
            raise BuildError(f"unsupported action in profile {profile['id']}: {action}")
        if action not in seen:
            seen.append(action)

    # Happ supports only one global priority per action bucket. Blocking is kept
    # first whenever a profile uses it; the remaining buckets retain their
    # first-occurrence order from autorules.
    if "reject" in seen:
        seen.remove("reject")
        seen.insert(0, "reject")
    for action in ("direct", "proxy", "reject"):
        if action not in seen:
            seen.append(action)
    return "-".join(ACTION_ORDER_NAMES[action] for action in seen)


def append_rule_values(
    buckets: dict[str, list[str]],
    rule: dict[str, Any],
    profile_id: str,
) -> None:
    try:
        sites_field, ip_field = ACTION_FIELDS[rule["action"]]
    except KeyError as exc:
        raise BuildError(f"unsupported action in profile {profile_id}") from exc

    selectors = SELECTORS & rule.keys()
    if len(selectors) != 1:
        raise BuildError(f"invalid selector in profile {profile_id}")
    selector = selectors.pop()
    values = rule[selector]

    if selector == "geosite":
        buckets[sites_field].extend(f"geosite:{value}" for value in values)
    elif selector == "geoip":
        buckets[ip_field].extend(f"geoip:{value}" for value in values)
    elif selector == "domains":
        buckets[sites_field].extend(values)
    else:
        buckets[ip_field].extend(values)


def render_profile(
    profile: dict[str, Any],
    repository: str,
    dist_ref: str,
    last_updated: int,
) -> dict[str, Any]:
    profile_id = profile["id"]
    default = profile["default"]
    if default not in {"direct", "proxy"}:
        raise BuildError(
            f"Happ cannot represent default action {default!r} in profile {profile_id}"
        )

    buckets = {
        "DirectSites": [],
        "DirectIp": [],
        "ProxySites": [],
        "ProxyIp": [],
        "BlockSites": [],
        "BlockIp": [],
    }
    for rule in profile["rules"]:
        append_rule_values(buckets, rule, profile_id)
    for field, values in buckets.items():
        buckets[field] = unique(values)

    dist_base = f"https://raw.githubusercontent.com/{repository}/{dist_ref}"
    return {
        "Name": profile_id,
        "GlobalProxy": "true" if default == "proxy" else "false",
        "UseChunkFiles": "true",
        "RemoteDNSType": "DoH",
        "RemoteDNSDomain": "https://cloudflare-dns.com/dns-query",
        "RemoteDNSIP": "1.1.1.1",
        "DomesticDNSType": "DoH",
        "DomesticDNSDomain": "https://dns.google/dns-query",
        "DomesticDNSIP": "8.8.8.8",
        "Geoipurl": f"{dist_base}/geoip.dat",
        "Geositeurl": f"{dist_base}/geosite.dat",
        "LastUpdated": str(last_updated),
        "DnsHosts": {
            "cloudflare-dns.com": "1.1.1.1",
            "dns.google": "8.8.8.8",
        },
        "RouteOrder": happ_route_order(profile),
        **buckets,
        "DomainStrategy": "IPIfNonMatch",
        "FakeDNS": "false",
    }


def encode_deeplink(profile: dict[str, Any], mode: str) -> str:
    compact_json = json.dumps(
        profile,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.b64encode(compact_json).decode("ascii")
    return f"happ://routing/{mode}/{encoded}"


def build(args: argparse.Namespace) -> None:
    if args.last_updated <= 0:
        raise BuildError("--last-updated must be a positive Unix timestamp")

    catalog = load_toml(args.catalog)
    categories = catalog["categories"]
    profile_ids = catalog["profiles"]["ids"]
    upstream = catalog["upstream"]
    source_name = f"{upstream['repository']}@{upstream['ref']}"
    validate_category_files(categories, args.geosite_in, args.geoip_in)

    profiles_dir = args.out / "profiles"
    links_dir = args.out / "links"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    links_dir.mkdir(parents=True, exist_ok=True)

    manifest_profiles: dict[str, dict[str, Any]] = {}
    for profile_id in profile_ids:
        profile_path = args.profiles / f"{profile_id}.toml"
        profile_source = load_toml(profile_path)
        if profile_source.get("id") != profile_id:
            raise BuildError(f"profile id mismatch: {profile_path}")
        profile = render_profile(
            profile_source,
            repository=args.repository,
            dist_ref=args.dist_ref,
            last_updated=args.last_updated,
        )
        profile_json = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
        (profiles_dir / f"{profile_id}.json").write_text(
            profile_json,
            encoding="utf-8",
        )
        add_link = encode_deeplink(profile, "add")
        onadd_link = encode_deeplink(profile, "onadd")
        (links_dir / f"{profile_id}.add.txt").write_text(
            add_link + "\n",
            encoding="utf-8",
        )
        (links_dir / f"{profile_id}.onadd.txt").write_text(
            onadd_link + "\n",
            encoding="utf-8",
        )
        manifest_profiles[profile_id] = {
            "global_proxy": profile["GlobalProxy"],
            "route_order": profile["RouteOrder"],
            "direct_sites": len(profile["DirectSites"]),
            "direct_ip": len(profile["DirectIp"]),
            "proxy_sites": len(profile["ProxySites"]),
            "proxy_ip": len(profile["ProxyIp"]),
            "block_sites": len(profile["BlockSites"]),
            "block_ip": len(profile["BlockIp"]),
        }

    index = [
        "# Happ routing profiles",
        f"# Source: {source_name}",
        "# Catalog: autorules",
        "",
        "| Profile | Default | Route order | JSON | Add | Add and activate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for profile_id in profile_ids:
        metadata = manifest_profiles[profile_id]
        default = "proxy" if metadata["global_proxy"] == "true" else "direct"
        index.append(
            f"| {profile_id} | {default} | {metadata['route_order']} | "
            f"[`json`](profiles/{profile_id}.json) | "
            f"[`add`](links/{profile_id}.add.txt) | "
            f"[`onadd`](links/{profile_id}.onadd.txt) |"
        )
    (args.out / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    (args.out / ".build-manifest.json").write_text(
        json.dumps(
            {
                "source": source_name,
                "last_updated": args.last_updated,
                "categories": {
                    "geosite": len(categories["geosite"]),
                    "geoip": len(categories["geoip"]),
                },
                "profiles": manifest_profiles,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Built {len(profile_ids)} Happ profiles from "
        f"{len(categories['geosite'])} geosite and "
        f"{len(categories['geoip'])} geoip categories"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--geosite-in", required=True, type=Path)
    parser.add_argument("--geoip-in", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--last-updated", required=True, type=int)
    parser.add_argument("--repository", default="x-netloc/happ-autorules")
    parser.add_argument("--dist-ref", default="dist")
    return parser.parse_args()


def main() -> int:
    try:
        build(parse_args())
    except (BuildError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
