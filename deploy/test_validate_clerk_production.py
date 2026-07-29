from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("validate-clerk-production.py")
SPEC = importlib.util.spec_from_file_location("validate_clerk_production", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def clerk_key(prefix: str, host: str) -> str:
    payload = base64.urlsafe_b64encode(f"{host}$".encode()).decode().rstrip("=")
    return f"{prefix}{payload}"


class ClerkProductionValidatorTests(unittest.TestCase):
    def run_validator(
        self,
        *arguments: str,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            env=(os.environ | (environment or {})),
            check=False,
            capture_output=True,
            text=True,
        )

    def write_runtime_files(
        self,
        root: Path,
        *,
        public_prefix: str = "pk_live_",
        secret_prefix: str = "sk_live_",
        public_host: str = "clerk.spyboxd.example",
        jwks_host: str = "clerk.spyboxd.example",
    ) -> tuple[Path, Path, Path, str]:
        publishable_key = clerk_key(public_prefix, public_host)
        frontend_env = root / "frontend.env"
        frontend_env.write_text(
            "\n".join(
                (
                    f"NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY={publishable_key}",
                    f"CLERK_SECRET_KEY={secret_prefix}synthetic-runtime-key",
                    "NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in",
                    "NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up",
                    "NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL=/",
                    "NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL=/",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        api_env = root / "api.env"
        api_env.write_text(
            "\n".join(
                (
                    f"CLERK_JWKS_URL=https://{jwks_host}/.well-known/jwks.json",
                    f"CLERK_ISSUER=https://{jwks_host}",
                    "CLERK_AUTHORIZED_PARTIES=https://spyboxd.com,https://www.spyboxd.com",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        manifest = root / ".spyboxd-release-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "frontend_public_environment": {
                        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": publishable_key,
                    }
                }
            ),
            encoding="utf-8",
        )
        return frontend_env, api_env, manifest, publishable_key

    @staticmethod
    def jwks(*, kid: str = "key-one", modulus: str = "modulus-one") -> dict[str, object]:
        return {
            "keys": [
                {
                    "kid": kid,
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "n": modulus,
                    "e": "AQAB",
                }
            ]
        }

    def test_build_requires_a_live_publishable_key(self) -> None:
        live_key = clerk_key("pk_live_", "clerk.spyboxd.example")
        result = self.run_validator(
            "build",
            environment={"NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": live_key},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        test_key = clerk_key("pk_test_", "sample.clerk.accounts.dev")
        rejected = self.run_validator(
            "build",
            environment={"NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": test_key},
        )
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("development publishable key", rejected.stderr)
        self.assertNotIn(test_key, rejected.stderr)

    def test_build_rejects_e2e_auth_bypass(self) -> None:
        live_key = clerk_key("pk_live_", "clerk.spyboxd.example")
        result = self.run_validator(
            "build",
            environment={
                "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": live_key,
                "SPYBOXD_E2E_AUTH_BYPASS": "enabled-only-in-tests",
            },
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("SPYBOXD_E2E_AUTH_BYPASS", result.stderr)
        self.assertNotIn("enabled-only-in-tests", result.stderr)

    def test_runtime_accepts_matching_live_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_requires_matching_canonical_clerk_issuer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            api.write_text(
                api.read_text(encoding="utf-8").replace(
                    "CLERK_ISSUER=https://clerk.spyboxd.example",
                    "CLERK_ISSUER=https://different.spyboxd.example",
                ),
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("CLERK_ISSUER", result.stderr)
        self.assertIn("different Clerk instances", result.stderr)

    def test_runtime_requires_clerk_issuer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            api.write_text(
                "\n".join(
                    line
                    for line in api.read_text(encoding="utf-8").splitlines()
                    if not line.startswith("CLERK_ISSUER=")
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing CLERK_ISSUER", result.stderr)

    def test_runtime_rejects_noncanonical_clerk_issuer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            api.write_text(
                api.read_text(encoding="utf-8").replace(
                    "CLERK_ISSUER=https://clerk.spyboxd.example",
                    "CLERK_ISSUER=https://clerk.spyboxd.example/",
                ),
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("canonical HTTPS origins", result.stderr)

    def test_runtime_requires_authorized_parties(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            api.write_text(
                "\n".join(
                    line
                    for line in api.read_text(encoding="utf-8").splitlines()
                    if not line.startswith("CLERK_AUTHORIZED_PARTIES=")
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing CLERK_AUTHORIZED_PARTIES", result.stderr)

    def test_runtime_rejects_unsafe_authorized_party(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            api.write_text(
                api.read_text(encoding="utf-8").replace(
                    "CLERK_AUTHORIZED_PARTIES=https://spyboxd.com,https://www.spyboxd.com",
                    "CLERK_AUTHORIZED_PARTIES=https://spyboxd.com,https://attacker.example",
                ),
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside the Spyboxd production sites", result.stderr)

    def test_runtime_rejects_non_https_or_non_origin_authorized_parties(self) -> None:
        invalid_origins = (
            "http://spyboxd.com",
            "https://spyboxd.com/path",
            "https://user@spyboxd.com",
            "https://spyboxd.com:443",
        )
        for invalid_origin in invalid_origins:
            with self.subTest(invalid_origin=invalid_origin):
                with tempfile.TemporaryDirectory() as directory:
                    frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
                    api.write_text(
                        api.read_text(encoding="utf-8").replace(
                            "CLERK_AUTHORIZED_PARTIES=https://spyboxd.com,https://www.spyboxd.com",
                            f"CLERK_AUTHORIZED_PARTIES={invalid_origin}",
                        ),
                        encoding="utf-8",
                    )
                    result = self.run_validator(
                        "runtime",
                        "--frontend-env",
                        str(frontend),
                        "--api-env",
                        str(api),
                        "--manifest",
                        str(manifest),
                    )
                self.assertEqual(result.returncode, 1)
                self.assertIn("CLERK_AUTHORIZED_PARTIES", result.stderr)

    def test_runtime_authorized_parties_must_include_primary_site(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            api.write_text(
                api.read_text(encoding="utf-8").replace(
                    "CLERK_AUTHORIZED_PARTIES=https://spyboxd.com,https://www.spyboxd.com",
                    "CLERK_AUTHORIZED_PARTIES=https://www.spyboxd.com",
                ),
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must include https://spyboxd.com", result.stderr)

    def test_remote_runtime_accepts_secret_and_frontend_from_same_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            with mock.patch.object(
                VALIDATOR,
                "_fetch_json",
                side_effect=(
                    {"id": "ins_production", "environment_type": "production"},
                    self.jwks(),
                    self.jwks(),
                ),
            ) as fetch_json:
                VALIDATOR.validate_runtime(
                    frontend,
                    api,
                    manifest,
                    verify_remote=True,
                )

        self.assertEqual(fetch_json.call_count, 3)
        self.assertEqual(
            fetch_json.call_args_list[0].args,
            (VALIDATOR.CLERK_BACKEND_INSTANCE_URL,),
        )
        self.assertEqual(
            fetch_json.call_args_list[1].args,
            (VALIDATOR.CLERK_BACKEND_JWKS_URL,),
        )
        self.assertEqual(
            fetch_json.call_args_list[2].args,
            ("https://clerk.spyboxd.example/.well-known/jwks.json",),
        )
        self.assertNotIn("secret_key", fetch_json.call_args_list[2].kwargs)

    def test_remote_runtime_rejects_secret_from_a_different_instance(self) -> None:
        secret_key = "sk_live_synthetic-runtime-key"
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            with mock.patch.object(
                VALIDATOR,
                "_fetch_json",
                side_effect=(
                    {"id": "ins_other", "environment_type": "production"},
                    self.jwks(kid="other-key", modulus="other-modulus"),
                    self.jwks(),
                ),
            ):
                with self.assertRaises(VALIDATOR.ConfigurationError) as raised:
                    VALIDATOR.validate_runtime(
                        frontend,
                        api,
                        manifest,
                        verify_remote=True,
                    )

        self.assertIn("different instances", str(raised.exception))
        self.assertNotIn(secret_key, str(raised.exception))

    def test_remote_runtime_rejects_non_production_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            with mock.patch.object(
                VALIDATOR,
                "_fetch_json",
                return_value={"id": "ins_development", "environment_type": "development"},
            ) as fetch_json:
                with self.assertRaises(VALIDATOR.ConfigurationError) as raised:
                    VALIDATOR.validate_runtime(
                        frontend,
                        api,
                        manifest,
                        verify_remote=True,
                    )

        self.assertIn("production instance", str(raised.exception))
        self.assertEqual(fetch_json.call_count, 1)

    def test_remote_http_failure_does_not_echo_secret(self) -> None:
        secret_key = "sk_live_do-not-print-this-secret"
        opener = mock.Mock()
        opener.open.side_effect = VALIDATOR.HTTPError(
            VALIDATOR.CLERK_BACKEND_INSTANCE_URL,
            401,
            "Unauthorized",
            {},
            None,
        )
        with mock.patch.object(VALIDATOR, "build_opener", return_value=opener):
            with self.assertRaises(VALIDATOR.ConfigurationError) as raised:
                VALIDATOR._fetch_json(
                    VALIDATOR.CLERK_BACKEND_INSTANCE_URL,
                    secret_key=secret_key,
                )

        self.assertIn("HTTP 401", str(raised.exception))
        self.assertNotIn(secret_key, str(raised.exception))

    def test_only_forward_release_requires_remote_verification(self) -> None:
        release_script = SCRIPT.with_name("release.sh").read_text(encoding="utf-8")
        rollback_script = SCRIPT.with_name("rollback.sh").read_text(encoding="utf-8")
        self.assertIn("--verify-remote", release_script)
        self.assertNotIn("--verify-remote", rollback_script)
        self.assertIn('"CLERK_ISSUER",', release_script)
        self.assertIn('"CLERK_AUTHORIZED_PARTIES",', release_script)

    def test_forward_release_validates_previous_clerk_manifest_before_mutation(self) -> None:
        release_script = SCRIPT.with_name("release.sh").read_text(encoding="utf-8")
        compatibility_marker = (
            'log "Validating the automatic rollback target against production Clerk configuration"'
        )
        compatibility_index = release_script.index(compatibility_marker)
        migration_index = release_script.index('log "Applying database migrations"')
        activation_index = release_script.index(f'log "Activating ${{FINAL_RELEASE}}"')
        compatibility_end = release_script.index("\nfi", compatibility_index)
        compatibility_block = release_script[compatibility_index:compatibility_end]

        self.assertLess(compatibility_index, migration_index)
        self.assertLess(compatibility_index, activation_index)
        self.assertIn('--manifest "${previous_manifest}"', compatibility_block)
        self.assertNotIn("--verify-remote", compatibility_block)
        self.assertIn(
            "current release has no immutable Clerk-compatible release manifest",
            release_script,
        )
        self.assertIn(
            "legacy in-place release cannot be retained as a Clerk-compatible rollback target",
            release_script,
        )

    def test_exact_development_manifest_is_eligible_for_bridge(self) -> None:
        revision = "a" * 40
        development_key = clerk_key("pk_test_", "sample.clerk.accounts.dev")
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / ".spyboxd-release-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "revision": revision,
                        "frontend_public_environment": {
                            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": development_key,
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_validator(
                "development-manifest",
                "--manifest",
                str(manifest),
                "--expected-revision",
                revision,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(development_key, result.stdout + result.stderr)

    def test_bridge_rejects_live_or_wrong_revision_source_manifest(self) -> None:
        revision = "a" * 40
        cases = (
            (clerk_key("pk_live_", "clerk.spyboxd.example"), revision),
            (clerk_key("pk_test_", "sample.clerk.accounts.dev"), "b" * 40),
        )
        for publishable_key, manifest_revision in cases:
            with self.subTest(manifest_revision=manifest_revision, key_prefix=publishable_key[:8]):
                with tempfile.TemporaryDirectory() as directory:
                    manifest = Path(directory) / ".spyboxd-release-manifest.json"
                    manifest.write_text(
                        json.dumps(
                            {
                                "format_version": 1,
                                "revision": manifest_revision,
                                "frontend_public_environment": {
                                    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": publishable_key,
                                },
                            }
                        ),
                        encoding="utf-8",
                    )
                    result = self.run_validator(
                        "development-manifest",
                        "--manifest",
                        str(manifest),
                        "--expected-revision",
                        revision,
                    )

                self.assertEqual(result.returncode, 1)
                self.assertNotIn(publishable_key, result.stdout + result.stderr)

    def test_clerk_bridge_is_exact_opt_in_and_never_restarts_dev_artifact(self) -> None:
        release_script = SCRIPT.with_name("release.sh").read_text(encoding="utf-8")
        workflow = (SCRIPT.parents[1] / ".github/workflows/deploy.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('readonly CLERK_BRIDGE_EDGE="${SPYBOXD_CLERK_BRIDGE_EDGE:-}"', release_script)
        self.assertIn('^([0-9a-f]{40}):([0-9a-f]{40})$', release_script)
        self.assertIn("development-manifest", release_script)
        self.assertIn("automatic rollback is unavailable", release_script)
        self.assertIn('old_release=""', release_script)
        self.assertIn("vars.PRODUCTION_CLERK_BRIDGE_EDGE", workflow)
        self.assertIn('"${previous_target}:${RELEASE_SHA}"', workflow)
        self.assertIn('SPYBOXD_CLERK_BRIDGE_EDGE="${CLERK_BRIDGE_EDGE}"', workflow)
        self.assertIn(
            "Stopped the failed Clerk bridge without activating the incompatible development artifact.",
            workflow,
        )
        self.assertIn(
            "Stopped the externally unhealthy Clerk bridge; no incompatible rollback was activated.",
            workflow,
        )

    def test_runtime_rejects_development_key_previous_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            development_key = clerk_key("pk_test_", "sample.clerk.accounts.dev")
            manifest.write_text(
                json.dumps(
                    {
                        "frontend_public_environment": {
                            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": development_key,
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match the runtime environment", result.stderr)
        self.assertNotIn(development_key, result.stderr)

    def test_runtime_rejects_development_keys_without_echoing_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, publishable_key = self.write_runtime_files(
                Path(directory),
                public_prefix="pk_test_",
                secret_prefix="sk_test_",
                public_host="sample.clerk.accounts.dev",
                jwks_host="sample.clerk.accounts.dev",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("development publishable key", result.stderr)
        self.assertNotIn(publishable_key, result.stderr)

    def test_runtime_rejects_development_secret_with_live_publishable_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(
                Path(directory),
                secret_prefix="sk_test_",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("development secret key", result.stderr)

    def test_runtime_rejects_frontend_and_backend_instance_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(
                Path(directory),
                jwks_host="different.spyboxd.example",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("different Clerk instances", result.stderr)

    def test_runtime_rejects_e2e_auth_bypass_in_environment_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            frontend.write_text(
                frontend.read_text(encoding="utf-8")
                + "SPYBOXD_E2E_AUTH_BYPASS=enabled-only-in-tests\n",
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("SPYBOXD_E2E_AUTH_BYPASS", result.stderr)
        self.assertNotIn("enabled-only-in-tests", result.stderr)

    def test_runtime_rejects_release_manifest_key_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, publishable_key = self.write_runtime_files(Path(directory))
            manifest.write_text(
                json.dumps(
                    {
                        "frontend_public_environment": {
                            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": clerk_key(
                                "pk_live_", "other.spyboxd.example"
                            ),
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match the runtime environment", result.stderr)
        self.assertNotIn(publishable_key, result.stderr)

    def test_runtime_accepts_frontend_api_as_jwks_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            api.write_text(
                "\n".join(
                    (
                        "CLERK_FRONTEND_API=https://clerk.spyboxd.example",
                        "CLERK_ISSUER=https://clerk.spyboxd.example",
                        "CLERK_AUTHORIZED_PARTIES=https://spyboxd.com",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_rejects_insecure_jwks_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frontend, api, manifest, _ = self.write_runtime_files(Path(directory))
            api.write_text(
                "\n".join(
                    (
                        "CLERK_JWKS_URL=http://clerk.spyboxd.example/.well-known/jwks.json",
                        "CLERK_ISSUER=https://clerk.spyboxd.example",
                        "CLERK_AUTHORIZED_PARTIES=https://spyboxd.com",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_validator(
                "runtime",
                "--frontend-env",
                str(frontend),
                "--api-env",
                str(api),
                "--manifest",
                str(manifest),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be an HTTPS Clerk origin", result.stderr)


if __name__ == "__main__":
    unittest.main()
