from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def test_cloud_run_cost_guards_and_single_image_are_explicit(self) -> None:
        script = (ROOT / "scripts" / "deploy_gcp.sh").read_text(encoding="utf-8")
        self.assertIn('--min-instances=0', script)
        self.assertIn('--max-instances=1', script)
        self.assertIn('--cpu-throttling', script)
        self.assertIn('--no-allow-unauthenticated', script)
        self.assertEqual(script.count('gcloud builds submit'), 1)
        self.assertIn('${CLOUD_RUN_REGION}-docker.pkg.dev', script)
        self.assertIn('GOOGLE_CLOUD_LOCATION:=global', script)
        self.assertIn('AGENT_REGISTRY_LOCATION:=global', script)
        self.assertIn("value(registryResource)", script)
        self.assertNotIn("--filter=\"displayName=", script)
        self.assertNotIn("gke", script.lower())
        self.assertNotIn("cloud sql", script.lower())

    def test_setup_uses_default_firestore_and_one_business_topic(self) -> None:
        script = (ROOT / "scripts" / "setup_gcp.sh").read_text(encoding="utf-8")
        self.assertIn("--database='(default)'", script)
        self.assertEqual(script.count("gcloud pubsub topics create"), 1)
        self.assertIn("enterprise-events", script)
        self.assertIn("roles/cloudtrace.agent", script)
        self.assertIn("gcloud pubsub topics add-iam-policy-binding", script)
        self.assertIn("roles/pubsub.publisher", script)
        self.assertNotIn("roles/telemetry.tracesWriter", script)

    def test_production_image_installs_google_runtime(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('pip install --no-cache-dir ".[google]"', dockerfile)
        self.assertIn('google-adk[a2a,agent-identity,mcp]', pyproject)

    def test_public_dashboard_script_exposes_only_recall(self) -> None:
        publish = (ROOT / "scripts" / "publish_dashboard.sh").read_text(encoding="utf-8")
        unpublish = (ROOT / "scripts" / "unpublish_dashboard.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("PUBLIC_DASHBOARD=true,ENABLE_PUBLIC_DEMO=true", publish)
        self.assertIn("PUBLIC_DEMO_DAILY_LIMIT=25", publish)
        self.assertIn("PUBLIC_DEMO_TTL_MINUTES=30", publish)
        self.assertIn("--member=allUsers", publish)
        self.assertIn("recallops-recall", publish)
        self.assertNotIn("recallops-supply", publish)
        self.assertNotIn("recallops-finance", publish)
        self.assertIn("remove-iam-policy-binding recallops-recall", unpublish)
        self.assertIn("PUBLIC_DASHBOARD=false,ENABLE_PUBLIC_DEMO=false", unpublish)

    def test_private_deployment_disables_public_demo_by_default(self) -> None:
        script = (ROOT / "scripts" / "deploy_gcp.sh").read_text(encoding="utf-8")
        self.assertIn("PUBLIC_DASHBOARD=false", script)
        self.assertIn("ENABLE_PUBLIC_DEMO=false", script)


if __name__ == "__main__":
    unittest.main()
