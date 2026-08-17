import base64
import gzip
import struct
import unittest

import skyblock_connector as connector


TEST_UUID = "0123456789abcdef0123456789abcdef"


def nbt_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def sample_inventory() -> str:
    # root compound -> list i -> one compound item -> Count + tag/ExtraAttributes/id
    data = bytearray(b"\x0a\x00\x00")
    data.extend(b"\x09" + nbt_string("i") + b"\x0a" + struct.pack(">i", 1))
    data.extend(b"\x01" + nbt_string("Count") + b"\x01")
    data.extend(b"\x0a" + nbt_string("tag"))
    data.extend(b"\x0a" + nbt_string("ExtraAttributes"))
    data.extend(b"\x08" + nbt_string("id") + nbt_string("MEDIUM_FISHING_SACK"))
    data.extend(b"\x00\x00\x00\x00")
    return base64.b64encode(gzip.compress(bytes(data))).decode("ascii")


class ConnectorTests(unittest.TestCase):
    def test_decode_inventory(self):
        items = connector.decode_inventory(sample_inventory())
        self.assertEqual(items[0]["id"], "MEDIUM_FISHING_SACK")
        self.assertEqual(items[0]["count"], 1)

    def test_build_snapshot(self):
        response = {
            "success": True,
            "profiles": [{
                "profile_id": "profile-id",
                "cute_name": "Apple",
                "selected": True,
                "banking": {"balance": 123},
                "members": {
                    TEST_UUID: {
                        "currencies": {"coin_purse": 45},
                        "player_data": {"experience": {"SKILL_FISHING": 260000}},
                        "inventory": {
                            "bag_contents": {"sacks_bag": {"data": sample_inventory()}},
                            "sacks_counts": {"RAW_FISH": 42, "EMPTY": 0},
                        },
                    }
                },
            }],
        }
        snapshot = connector.build_snapshot(
            response,
            TEST_UUID,
            "ExamplePlayer",
            "Apple",
            {"limit": "120", "remaining": "119", "reset_seconds": "30"},
            {
                "item_names": {"RAW_FISH": "Raw Cod"},
                "fishing_levels": [
                    {"level": 22, "total_xp": 1222425},
                    {"level": 23, "total_xp": 1722425},
                ],
            },
        )
        self.assertEqual(snapshot["owned_sacks"][0]["id"], "MEDIUM_FISHING_SACK")
        self.assertEqual(snapshot["sack_counts"], {"RAW_FISH": 42})
        self.assertEqual(snapshot["skills"]["fishing_xp"], 260000)
        self.assertEqual(snapshot["currency"]["bank"], 123)

    def test_normalize_uuid(self):
        self.assertEqual(
            connector.normalize_uuid("01234567-89ab-cdef-0123-456789abcdef"),
            TEST_UUID,
        )

    def test_skill_progress(self):
        levels = [
            {"level": 22, "total_xp": 1222425},
            {"level": 23, "total_xp": 1722425},
            {"level": 24, "total_xp": 2322425},
        ]
        progress = connector.skill_progress(1685200, levels)
        self.assertEqual(progress["level"], 22)
        self.assertEqual(progress["next_level"], 23)
        self.assertEqual(progress["remaining_to_next"], 37225)


if __name__ == "__main__":
    unittest.main()
