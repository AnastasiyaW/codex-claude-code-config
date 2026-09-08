"""Exercise the real CLI against an isolated desktop metadata fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class SessionFindTests(unittest.TestCase):
    def test_searches_id_and_prints_packaged_restore_command(self):
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            if sys.platform == "win32":
                appdata = home / "Roaming"
                base = appdata / "Claude"
            elif sys.platform == "darwin":
                base = home / "Library" / "Application Support" / "Claude"
            else:
                base = home / ".config" / "Claude"
            session = base / "claude-code-sessions" / "account" / "org" / "local_fixture.json"
            session.parent.mkdir(parents=True)
            session.write_text(json.dumps({"sessionId": "abcd1234-unique-session", "title": "Unrelated title", "cwd": "project", "lastActivityAt": 1700000000000}), encoding="utf-8")
            environment = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
            if sys.platform == "win32":
                environment["APPDATA"] = str(appdata)
            result = subprocess.run([sys.executable, str(scripts / "sessions_find.py"), "abcd1234"], env=environment, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("# Found 1 sessions", result.stdout)
            self.assertIn(str(scripts / "sessions_restore.py"), result.stdout)
            self.assertTrue((scripts / "sessions_restore.py").is_file())


if __name__ == "__main__":
    unittest.main()
