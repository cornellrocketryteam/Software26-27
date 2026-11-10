"""No real serial device or network connection is used by these tests."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("command_listener", ROOT / "ground-station/LaunchButton/pc_listener.py")
listener = importlib.util.module_from_spec(spec)
spec.loader.exec_module(listener)
NONCE = "0123456789abcdef0123456789abcdef"


def ready(nonce=NONCE):
    return f"READY {nonce} btn=0 key=0 dis=0\n".encode()


def command(token, sequence=1, nonce=NONCE):
    return f"CMD {nonce} {sequence} {token}\n".encode()


class ListenerTests(unittest.TestCase):
    def test_legacy_backlog_cannot_authorize_a_new_connection(self):
        session = listener.CommandSession({"launch", "fsw_key_arm"}, nonce=NONCE)
        self.assertEqual(session.feed(b"DBG:btn=0 key=0 dis=0\n<KA>\n<L>\n"), [])
        self.assertEqual(session.feed(command("<KA>")), [])
        self.assertEqual(session.feed(ready() + command("<KA>")), ["fsw_key_arm"])

    def test_monitor_only_by_default(self):
        session = listener.CommandSession()
        self.assertEqual(session.feed(ready() + command("<L>") + b"<L>\n<KA>\n<X>\n"), [])

    def test_exact_frames_allowlist_and_partial_input(self):
        session = listener.CommandSession({"fsw_key_arm"}, nonce=NONCE)
        session.feed(ready())
        self.assertEqual(session.feed(b"noise <KA>\n<L>\n<X>\n"), [])
        frame = command("<KA>")
        self.assertEqual(session.feed(frame[:-3]), [])
        self.assertEqual(session.feed(frame[-3:]), ["fsw_key_arm"])
        self.assertEqual(session.feed(command("<L>", 2)), [])

    def test_old_nonce_duplicate_and_out_of_order_are_rejected(self):
        session = listener.CommandSession({"launch"}, nonce=NONCE)
        self.assertEqual(session.feed(ready("old") + command("<L>", nonce="old")), [])
        session.feed(ready())
        self.assertEqual(session.feed(command("<L>", 2)), ["launch"])
        self.assertEqual(session.feed(command("<L>", 2) + command("<L>", 1)), [])
        # A repeated READY must not reset anti-replay sequence state.
        self.assertEqual(session.feed(ready() + command("<L>", 2)), [])

    def test_new_session_does_not_replay_partial_frames_or_ready_state(self):
        old = listener.CommandSession({"launch"}, nonce=NONCE)
        old.feed(ready() + command("<L>")[:-2])
        new = listener.CommandSession({"launch"}, nonce="a" * 32)
        self.assertEqual(new.feed(b">\n" + ready() + command("<L>")), [])

    def test_commanding_requires_an_unpredictable_session_identifier(self):
        with self.assertRaises(ValueError): listener.CommandSession({"launch"})
        with self.assertRaises(ValueError): listener.CommandSession({"launch"}, nonce="bad nonce")

    def test_overlong_or_nonascii_frame_is_discarded(self):
        session = listener.CommandSession({"launch"}, nonce=NONCE)
        session.feed(ready())
        self.assertEqual(session.feed(b"z" * 1000 + command("<L>") + b"\xff" + command("<L>")), [])
        self.assertEqual(session.feed(command("<L>")), ["launch"])

    def test_device_selection_rejects_generic_or_ambiguous_picos(self):
        class Port:
            def __init__(self, device, serial, product="LaunchButton"):
                self.device, self.serial_number, self.product = device, serial, product
                self.vid, self.pid = 0xC0DE, 0xCAFE
        candidates = [Port("/dev/a", "123"), Port("/dev/b", "123")]
        with self.assertRaises(ValueError): listener.select_device(candidates, "123")
        with self.assertRaises(ValueError): listener.select_device([Port("/dev/a", "123", "FSW")], "123")
        self.assertEqual(listener.select_device(candidates, "different", explicit="/dev/serial/by-id/button"), "/dev/serial/by-id/button")
        self.assertEqual(listener.select_device(candidates[:1], "123"), "/dev/a")


if __name__ == "__main__": unittest.main()
