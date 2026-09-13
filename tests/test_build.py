import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.build import (
    BuildError,
    build,
    encode_deeplink,
    happ_route_order,
    render_profile,
    validate_category_files,
)


class ProfileTests(unittest.TestCase):
    def test_happ_uses_block_first_when_profile_rejects(self) -> None:
        profile = {
            "id": "no-ads",
            "rules": [
                {"action": "direct", "geosite": ["private"]},
                {"action": "reject", "geosite": ["ads"]},
                {"action": "direct", "geosite": ["local"]},
            ],
        }

        self.assertEqual(happ_route_order(profile), "block-direct-proxy")

    def test_profile_rules_are_grouped_for_happ(self) -> None:
        profile = {
            "id": "example",
            "default": "proxy",
            "rules": [
                {"action": "direct", "geosite": ["private"]},
                {"action": "direct", "geoip": ["private"]},
                {"action": "proxy", "domains": ["domain:example.com"]},
                {"action": "reject", "cidrs": ["192.0.2.0/24"]},
            ],
        }

        rendered = render_profile(profile, "owner/repo", "dist", 1_700_000_000)

        self.assertEqual(rendered["GlobalProxy"], "true")
        self.assertEqual(rendered["RouteOrder"], "block-direct-proxy")
        self.assertEqual(rendered["DirectSites"], ["geosite:private"])
        self.assertEqual(rendered["DirectIp"], ["geoip:private"])
        self.assertEqual(rendered["ProxySites"], ["domain:example.com"])
        self.assertEqual(rendered["BlockIp"], ["192.0.2.0/24"])
        self.assertEqual(
            rendered["Geositeurl"],
            "https://raw.githubusercontent.com/owner/repo/dist/geosite.dat",
        )

    def test_deeplink_round_trip(self) -> None:
        profile = {"Name": "тест", "GlobalProxy": "false"}

        link = encode_deeplink(profile, "onadd")
        encoded = link.removeprefix("happ://routing/onadd/")
        decoded = json.loads(base64.b64decode(encoded).decode("utf-8"))

        self.assertEqual(decoded, profile)

    def test_reject_cannot_be_the_default(self) -> None:
        profile = {
            "id": "reject-default",
            "default": "reject",
            "rules": [{"action": "reject", "geosite": ["ads"]}],
        }

        with self.assertRaises(BuildError):
            render_profile(profile, "owner/repo", "dist", 1_700_000_000)


class BuildTests(unittest.TestCase):
    def test_missing_catalog_category_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "geosite").mkdir()
            (root / "geoip").mkdir()

            with self.assertRaises(BuildError):
                validate_category_files(
                    {"geosite": ["missing"], "geoip": ["missing"]},
                    root / "geosite",
                    root / "geoip",
                )

    def test_build_discovers_profiles_from_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "profiles").mkdir()
            (root / "geosite").mkdir()
            (root / "geoip").mkdir()
            (root / "catalog.toml").write_text(
                """schema_version = 1

[upstream]
repository = "owner/upstream"
ref = "release"
geosite_asset = "geosite.dat"
geoip_asset = "geoip.dat"

[categories]
geosite = ["private"]
geoip = ["private"]

[profiles]
ids = ["example"]
""",
                encoding="utf-8",
            )
            (root / "profiles/example.toml").write_text(
                """schema_version = 1
id = "example"
description = "Example profile."
default = "direct"

[[rules]]
action = "proxy"
geosite = ["private"]

[[rules]]
action = "proxy"
geoip = ["private"]
""",
                encoding="utf-8",
            )
            (root / "geosite/geosite_private.txt").write_text("example\n")
            (root / "geoip/geoip_private.txt").write_text("192.0.2.0/24\n")
            args = SimpleNamespace(
                catalog=root / "catalog.toml",
                profiles=root / "profiles",
                geosite_in=root / "geosite",
                geoip_in=root / "geoip",
                out=root / "out",
                last_updated=1_700_000_000,
                repository="owner/repo",
                dist_ref="dist",
            )

            build(args)

            profile_path = root / "out/profiles/example.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(profile["GlobalProxy"], "false")
            self.assertEqual(profile["ProxySites"], ["geosite:private"])
            self.assertTrue((root / "out/links/example.add.txt").is_file())
            self.assertTrue((root / "out/links/example.onadd.txt").is_file())
            manifest = json.loads(
                (root / "out/.build-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["categories"], {"geosite": 1, "geoip": 1})
            self.assertEqual(
                manifest["profiles"]["example"]["route_order"],
                "proxy-direct-block",
            )


if __name__ == "__main__":
    unittest.main()
