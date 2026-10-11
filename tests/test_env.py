import os, tempfile, unittest
from pathlib import Path
from jobagent.env import load_env


class Env(unittest.TestCase):
    def test_loads_without_overriding_and_enforces_perms(self):
        d = Path(tempfile.mkdtemp()); f = d / ".env"
        f.write_text("# c\nT_A='one'\nT_B=two\n"); f.chmod(0o644)
        with self.assertRaises(PermissionError):
            load_env(f)
        f.chmod(0o600); os.environ["T_B"] = "keep"
        load_env(f)
        self.assertEqual((os.environ["T_A"], os.environ["T_B"]), ("one", "keep"))


if __name__ == "__main__":
    unittest.main()
