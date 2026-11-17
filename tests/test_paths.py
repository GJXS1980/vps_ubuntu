import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
import ssr_paths


class LayoutTests(unittest.TestCase):
    def test_existing_layout_and_ambiguity(self):
        temporary = ROOT / '.test-tmp'
        temporary.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as directory:
            root = Path(directory)
            first = (root / 'first.json', root / 'first.py')
            legacy = (root / 'legacy.json', root / 'legacy.py')
            with patch.object(ssr_paths, 'LAYOUTS', (first, legacy)):
                with self.assertRaises(ValueError):
                    ssr_paths.installation()
                for path in legacy:
                    path.touch()
                self.assertEqual(ssr_paths.installation(), legacy)
                self.assertEqual(ssr_paths.server_for(legacy[0]), legacy[1])
                for path in first:
                    path.touch()
                with self.assertRaisesRegex(ValueError, '两套'):
                    ssr_paths.installation()
                with self.assertRaises(ValueError):
                    ssr_paths.server_for(root / 'unknown.json')
