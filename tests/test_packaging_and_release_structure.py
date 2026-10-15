import os
import stat
import subprocess
import unittest
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class TestPackagingAndReleaseStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parent.parent
        cls.packaging_dir = cls.project_root / "packaging"
        cls.linux_dir = cls.packaging_dir / "linux"
        cls.macos_dir = cls.packaging_dir / "macos"
        cls.windows_dir = cls.packaging_dir / "windows"
        cls.workflow_file = cls.project_root / ".github" / "workflows" / "release.yml"
        cls.readme_file = cls.project_root / "README.md"

    def test_install_script_syntax_and_dry_run(self):
        install_sh = self.linux_dir / "install.sh"
        self.assertTrue(install_sh.is_file(), "install.sh must exist")
        self.assertTrue(os.access(install_sh, os.X_OK), "install.sh must be executable")

        # Syntax check via bash -n
        res = subprocess.run(["bash", "-n", str(install_sh)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"bash -n failed: {res.stderr}")

        # Help flag
        res = subprocess.run([str(install_sh), "--help"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("usage:", res.stdout.lower())
        self.assertIn("--prefix", res.stdout)
        self.assertIn("--uninstall", res.stdout)
        self.assertIn("--dry-run", res.stdout)

        # Dry run flag
        res = subprocess.run([str(install_sh), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("[DRY-RUN]", res.stdout)

    def test_linux_packaging_scripts(self):
        scripts = [
            self.linux_dir / "build_deb.sh",
            self.linux_dir / "build_tarball.sh",
            self.linux_dir / "build_rpm.sh",
            self.linux_dir / "build_appimage.sh",
        ]
        for script in scripts:
            self.assertTrue(script.is_file(), f"{script.name} must exist")
            self.assertTrue(os.access(script, os.X_OK), f"{script.name} must be executable")

            # Syntax check
            res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Syntax check failed on {script.name}: {res.stderr}")

            # Dry run check
            res = subprocess.run([str(script), "--dry-run"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Dry-run failed on {script.name}: {res.stderr}")
            self.assertIn("[DRY-RUN]", res.stdout)

    def test_macos_packaging_script(self):
        build_dmg = self.macos_dir / "build_dmg.sh"
        self.assertTrue(build_dmg.is_file(), "build_dmg.sh must exist")
        self.assertTrue(os.access(build_dmg, os.X_OK), "build_dmg.sh must be executable")

        res = subprocess.run(["bash", "-n", str(build_dmg)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax check failed on build_dmg.sh: {res.stderr}")

        res = subprocess.run([str(build_dmg), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Dry-run failed on build_dmg.sh: {res.stderr}")
        self.assertIn("[DRY-RUN]", res.stdout)

    def test_windows_inno_setup_config(self):
        iss_file = self.windows_dir / "installer.iss"
        self.assertTrue(iss_file.is_file(), "installer.iss must exist")
        content = iss_file.read_text(encoding="utf-8")
        self.assertIn("OutputBaseFilename=ai-dubber-ultimate-v{#MyAppVersion}-windows-x64-setup", content)

    def test_release_workflow_structure(self):
        self.assertTrue(self.workflow_file.is_file(), "release.yml must exist")
        content = self.workflow_file.read_text(encoding="utf-8")

        # Verify YAML structure if pyyaml is installed
        if HAS_YAML:
            parsed = yaml.safe_load(content)
            self.assertIn("jobs", parsed)
            self.assertIn("package-portable", parsed["jobs"])
            self.assertIn("package-frozen", parsed["jobs"])
            self.assertIn("publish-release", parsed["jobs"])

        # Check required release assets and conventions
        self.assertIn("SHA256SUMS.txt", content)
        self.assertIn("ai-dubber-ultimate", content)
        self.assertIn("windows-x64-portable", content)
        self.assertIn("linux-x86_64-portable", content)
        self.assertIn("macos-universal", content)
        self.assertIn("build_tarball.sh", content)
        self.assertIn("build_deb.sh", content)
        self.assertIn("build_appimage.sh", content)
        self.assertIn("build_rpm.sh", content)

        # Check release body format matches user specification
        self.assertIn("### Windows", content)
        self.assertIn("### macOS", content)
        self.assertIn("### Linux", content)
        self.assertIn("AppImage", content)
        self.assertIn("Flatpak", content)
        self.assertIn("Debian/Ubuntu", content)
        self.assertIn("Fedora/RHEL/openSUSE", content)
        self.assertIn("Tarball", content)
        self.assertIn("./install.sh", content)
        self.assertIn("$env:QT_OPENGL=\"software\"", content)

    def test_readme_release_documentation(self):
        self.assertTrue(self.readme_file.is_file(), "README.md must exist")
        content = self.readme_file.read_text(encoding="utf-8")

        # Check release table presence and markdown structure
        self.assertIn("Releases & Downloads", content)
        self.assertIn("### Windows", content)
        self.assertIn("### macOS", content)
        self.assertIn("### Linux", content)
        self.assertIn("AppImage", content)
        self.assertIn("Flatpak", content)
        self.assertIn("Debian/Ubuntu", content)
        self.assertIn("Fedora/RHEL/openSUSE", content)
        self.assertIn("Tarball", content)
        self.assertIn("./install.sh", content)
        self.assertIn("SHA256SUMS.txt", content)
        self.assertIn("$env:QT_OPENGL=\"software\"", content)
        self.assertIn("--prefix /usr/local", content)


    def test_pyinstaller_spec_configuration(self):
        spec_file = self.packaging_dir / "ai_dubber.spec"
        self.assertTrue(spec_file.is_file(), "ai_dubber.spec must exist")
        content = spec_file.read_text(encoding="utf-8")

        # Must enforce absolute workpath/distpath and create workpath
        self.assertIn("PyInstaller.config.CONF['workpath']", content)
        self.assertIn("os.makedirs(workpath_dir, exist_ok=True)", content)

        # Must restrict pathex to src_dir to avoid scanning 20+ GB root folders
        self.assertIn("pathex=[src_dir]", content)
        self.assertNotIn("pathex=[src_dir, project_root]", content)

    def test_main_startup_environment_isolation(self):
        main_file = self.project_root / "src" / "main.py"
        self.assertTrue(main_file.is_file(), "main.py must exist")
        content = main_file.read_text(encoding="utf-8")

        # os.chdir must be guarded in _init_app_environment, not top-level
        self.assertIn("def _init_app_environment():", content)
        self.assertIn("if __name__ == '__main__':", content)
        self.assertIn("_init_app_environment()", content)

    def test_build_deb_fast_compression(self):
        deb_script = self.linux_dir / "build_deb.sh"
        content = deb_script.read_text(encoding="utf-8")

        # Must configure fast compression (-Zgzip or -Zzstd)
        self.assertIn("-Zgzip", content)
        self.assertIn("-Zzstd", content)
        self.assertIn("DEB_COMPRESSION", content)


if __name__ == "__main__":
    unittest.main()
