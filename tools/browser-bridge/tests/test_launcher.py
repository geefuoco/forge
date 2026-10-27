import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


LAUNCHER = Path(__file__).resolve().parents[1] / "launch.py"


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="forge launcher ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.desktop = self.root / "forge-gui-desktop"
        (self.desktop / "target" / "classes").mkdir(parents=True)
        self.script = self.root / "tools" / "browser-bridge" / "launch.py"
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(LAUNCHER, self.script)
        (self.root / ".mvn").mkdir()
        (self.root / ".mvn" / "maven.config").write_text("--settings\n./.mvn/local-settings.xml\n")
        (self.root / ".mvn" / "local-settings.xml").write_text("<settings/>")
        (self.desktop / "pom.xml").write_text(
            '<project xmlns="http://maven.apache.org/POM/4.0.0"><properties>'
            '<addopen.java.args>--add-opens java.base/java.lang=ALL-UNNAMED</addopen.java.args>'
            '</properties></project>'
        )
        self.home = self.root / "home"
        self.calls = []

    def run_launcher(self, extra_args=(), classpath=None):
        environment = {"APPDATA": "desktop-roaming", "LOCALAPPDATA": "desktop-local"}
        if classpath is not None:
            environment["FORGE_BRIDGE_CLASSPATH"] = classpath

        def run(command, **kwargs):
            self.calls.append((command, kwargs))
            if command[0] == "mvn":
                settings = Path(kwargs["cwd"]) / ".mvn" / "local-settings.xml"
                self.assertTrue(settings.is_file(), f"Maven cannot resolve {settings}")
                self.assertEqual(kwargs["cwd"], self.root)
                self.assertEqual(command[command.index("-f") + 1], str(self.desktop / "pom.xml"))
                output = next(arg.split("=", 1)[1] for arg in command if arg.startswith("-Dmdep.outputFile="))
                Path(output).write_text("dependency.jar\n")
            return subprocess.CompletedProcess(command, 0)

        args = [str(self.script), "--origin", "https://neoforge.example", *extra_args]
        with patch.dict(os.environ, environment, clear=True), \
                patch("sys.argv", args), \
                patch("pathlib.Path.home", return_value=self.home), \
                patch("shutil.which", side_effect=lambda command: command), \
                patch("subprocess.run", side_effect=run):
            runpy.run_path(str(self.script), run_name="__main__")

    def test_maven_resolves_root_settings_and_desktop_dependencies(self):
        self.run_launcher()
        self.assertEqual([command[0] for command, _ in self.calls], ["mvn", "javac", "java"])
        compile_command, compile_options = self.calls[1]
        expected = str(self.desktop / "target" / "classes") + os.pathsep + "dependency.jar"
        self.assertEqual(compile_command[compile_command.index("-cp") + 1], expected)
        self.assertEqual(compile_options["cwd"], self.desktop)
        self.assertTrue(all(options["check"] for _, options in self.calls))

    def test_classpath_override_does_not_run_maven(self):
        self.run_launcher(classpath="custom-engine.jar")
        self.assertEqual([command[0] for command, _ in self.calls], ["javac", "java"])
        command, _ = self.calls[0]
        self.assertEqual(command[command.index("-cp") + 1], "custom-engine.jar")

    def test_runtime_retains_desktop_working_directory_and_private_profile(self):
        profile = self.root / "custom profile"
        self.run_launcher(["--profile", str(profile)], classpath="engine.jar")
        command, options = self.calls[-1]
        self.assertEqual(options["cwd"], self.desktop)
        self.assertIn("--add-opens", command)
        self.assertIn("java.base/java.lang=ALL-UNNAMED", command)
        self.assertIn("-Duser.home=" + str(profile), command)
        self.assertEqual(options["env"]["APPDATA"], str(profile / "AppData" / "Roaming"))
        self.assertEqual(options["env"]["LOCALAPPDATA"], str(profile / "AppData" / "Local"))
        self.assertEqual(command[-2:], ["forge.browser.Bridge", "https://neoforge.example"])
        self.assertTrue(profile.is_dir())


if __name__ == "__main__":
    unittest.main()
