from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SubmissionReadinessTests(unittest.TestCase):
    def test_public_readme_contains_taskmaster_evidence_and_no_private_doc_links(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for evidence in (
            "Taskmaster",
            "assets/architecture.svg",
            "Google Agent Development Kit",
            "Gemini 3.5 Flash-Lite",
            "Agent Registry",
            "A2A",
            "scripts/setup_gcp.sh",
            "What we learned",
            "not used by the committed demonstration dataset",
        ):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, readme)
        self.assertNotIn("docs/", readme)
        self.assertNotIn("HANDOFF.md", readme)
        self.assertNotIn("presentation/", readme)

    def test_architecture_diagram_is_accessible_valid_svg(self) -> None:
        path = ROOT / "assets" / "architecture.svg"
        root = ET.parse(path).getroot()
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual(root.attrib.get("role"), "img")
        self.assertIsNotNone(root.find("{http://www.w3.org/2000/svg}title"))
        self.assertIsNotNone(root.find("{http://www.w3.org/2000/svg}desc"))


if __name__ == "__main__":
    unittest.main()
