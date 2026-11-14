import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import sysfix  # noqa: E402  (GTK is only imported lazily, so the Mac can run these)

WPA = """bssid=aa:bb:cc:dd:ee:ff
freq=2437
ssid=Home Net
id=0
mode=station
pairwise_cipher=CCMP
wpa_state=COMPLETED
ip_address=192.168.1.50
"""


def good_state(**overrides):
    state = {
        "wifi": {"wpa_state": "COMPLETED", "ssid": "Home"},
        "ip": "192.168.1.50", "gateway": "192.168.1.1", "power_save": False,
        "services": {"ssh": "active", "lightdm": "active"},
        "failed": [], "gateway_ok": True, "internet_ok": True, "dns_ok": True,
    }
    state.update(overrides)
    return state


class ParseTests(unittest.TestCase):
    def test_wpa_status(self):
        info = sysfix.parse_wpa_status(WPA)
        self.assertEqual(info["ssid"], "Home Net")
        self.assertEqual(info["wpa_state"], "COMPLETED")
        self.assertEqual(sysfix.parse_wpa_status(""), {})
        self.assertEqual(sysfix.parse_wpa_status(None), {})

    def test_ipv4(self):
        line = "3: mlan0    inet 192.168.1.50/24 brd 192.168.1.255 scope global dynamic mlan0\\       valid_lft 1 preferred_lft 1"
        self.assertEqual(sysfix.parse_ipv4(line), "192.168.1.50")
        self.assertEqual(sysfix.parse_ipv4(""), "")

    def test_gateway(self):
        self.assertEqual(
            sysfix.default_gateway("default via 192.168.1.1 dev mlan0 src 192.168.1.50 metric 302 \n"),
            "192.168.1.1")
        self.assertEqual(sysfix.default_gateway(""), "")
        self.assertEqual(sysfix.default_gateway("192.168.1.0/24 dev mlan0 proto dhcp"), "")

    def test_power_save(self):
        self.assertIs(sysfix.parse_power_save("Power save: on\n"), True)
        self.assertIs(sysfix.parse_power_save("Power save: off"), False)
        self.assertIsNone(sysfix.parse_power_save("command failed: No such device (-19)"))

    def test_failed_units(self):
        text = ("● dhcpcd.service loaded failed failed DHCP Client Daemon\n"
                "nmbd.service   loaded failed failed Samba NMB Daemon\n")
        self.assertEqual(sysfix.parse_failed_units(text), ["dhcpcd.service", "nmbd.service"])
        self.assertEqual(sysfix.parse_failed_units(""), [])

    def test_is_active(self):
        self.assertEqual(sysfix.parse_is_active(["a", "b", "c"], "active\ninactive\n"),
                         {"a": "active", "b": "inactive", "c": "unknown"})


class HealthTests(unittest.TestCase):
    def test_all_good(self):
        self.assertEqual(sysfix.health(good_state()), ("ok", "All good"))

    def test_not_checked_is_not_a_problem(self):
        state = good_state(gateway_ok=None, internet_ok=None, dns_ok=None)
        self.assertEqual(sysfix.health(state), ("ok", "All good"))

    def test_wifi_down_wins(self):
        state = good_state(wifi={"wpa_state": "SCANNING"}, ip="", gateway_ok=False, internet_ok=False)
        self.assertEqual(sysfix.health(state), ("bad", "Wi-Fi not connected"))

    def test_router_unreachable_hides_no_internet(self):
        state = good_state(gateway_ok=False, internet_ok=False)
        self.assertEqual(sysfix.health(state), ("bad", "router not reachable"))

    def test_service_down_counts_others(self):
        state = good_state(services={"ssh": "failed", "lightdm": "active"},
                           failed=["ssh.service"], power_save=True)
        self.assertEqual(sysfix.health(state), ("bad", "ssh is failed (+2 more)"))

    def test_warnings(self):
        self.assertEqual(sysfix.health(good_state(internet_ok=False, dns_ok=False)), ("warn", "no internet"))
        self.assertEqual(sysfix.health(good_state(dns_ok=False)), ("warn", "DNS not working"))
        self.assertEqual(sysfix.health(good_state(failed=["a.service", "b.service"])),
                         ("warn", "2 failed units"))
        self.assertEqual(sysfix.health(good_state(power_save=True)), ("warn", "Wi-Fi power save is on"))


class RunTests(unittest.TestCase):
    def test_run_never_raises(self):
        self.assertEqual(sysfix.run(["/nonexistent/cmd"])[0], False)
        ok, out = sysfix.run(["sh", "-c", "echo hi; exit 3"])
        self.assertFalse(ok)
        self.assertEqual(out, "hi")
        self.assertEqual(sysfix.run(["sleep", "5"], timeout=0.2), (False, "timed out"))


if __name__ == "__main__":
    unittest.main()
