import contextlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import release
import source_version as source


@contextlib.contextmanager
def cwd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def git(path, *args):
    location = ["--git-dir", str(path)] if path.name.endswith(".git") else ["-C", str(path)]
    return subprocess.run(
        ["git", *location, *args], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def copy_source(destination):
    for path in source.SOURCE_PATHS:
        (destination / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, destination / path)


def entry(tag="v9.8.7", draft=False):
    return {"id": 42, "tag_name": tag, "draft": draft, "prerelease": False}


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        copy_source(self.root)
        self.current = source.read(self.root)

    def plist(self, **values):
        path = self.root / source.PLIST
        data = plistlib.loads(path.read_bytes())
        data.update(values)
        path.write_bytes(plistlib.dumps(data))

    def test_live_metadata_and_all_bump_modes(self):
        parts = list(map(int, self.current.split(".")))
        for mode, expected in (
            ("patch", [parts[0], parts[1], parts[2] + 1]),
            ("minor", [parts[0], parts[1] + 1, 0]),
            ("major", [parts[0] + 1, 0, 0]),
        ):
            with self.subTest(mode=mode):
                copy_source(self.root)
                self.assertEqual(source.bump(mode, self.root), ".".join(map(str, expected)))
                self.assertEqual(source.read(self.root), ".".join(map(str, expected)))
                self.assertNotIn("CFBundleVersion",
                                 plistlib.loads((self.root / source.PLIST).read_bytes()))

    def test_invalid_marketing_values_and_missing_settings(self):
        path = self.root / source.PROJECT
        original = path.read_text()
        for bad in ("1.2", "v1.2.3", "01.2.3", "1.2.3-beta", "$(UNKNOWN)", ""):
            with self.subTest(bad=bad):
                path.write_text(original.replace(f"MARKETING_VERSION = {self.current};",
                                                 f"MARKETING_VERSION = {bad};", 1))
                with self.assertRaises(ValueError):
                    source.read(self.root)
        path.write_text(original.replace(f"MARKETING_VERSION = {self.current};", "", 1))
        with self.assertRaises(ValueError):
            source.read(self.root)

    def test_current_project_drift_and_cyclic_reference(self):
        path = self.root / source.PROJECT
        original = path.read_text()
        for bad in ("0.0.0" if self.current != "0.0.0" else "0.0.1",
                    '"$(CURRENT_PROJECT_VERSION)"', '"$(UNKNOWN)"', "17"):
            path.write_text(original.replace(
                f"CURRENT_PROJECT_VERSION = {self.current};", f"CURRENT_PROJECT_VERSION = {bad};", 1))
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                source.bump("patch", self.root)

    def test_plist_invalid_drift_and_missing(self):
        for key in ("CFBundleShortVersionString", "CFBundleVersion"):
            for value in ("0.0.0" if self.current != "0.0.0" else "0.0.1",
                          "$(UNKNOWN)", "$(PRODUCT_NAME)", "", "1.2", 123):
                with self.subTest(key=key, value=value):
                    copy_source(self.root)
                    self.plist(**{key: value})
                    with self.assertRaises(ValueError):
                        source.read(self.root)
        copy_source(self.root)
        path = self.root / source.PLIST
        data = plistlib.loads(path.read_bytes())
        del data["CFBundleShortVersionString"]
        path.write_bytes(plistlib.dumps(data))
        with self.assertRaises(ValueError):
            source.read(self.root)

    def test_valid_refs_preserved_and_optional_bundle_version_coordinated(self):
        for reference in source.REFERENCES:
            with self.subTest(reference=reference):
                copy_source(self.root)
                self.plist(CFBundleShortVersionString=reference, CFBundleVersion=reference)
                path = self.root / source.PROJECT
                path.write_text(path.read_text().replace(
                    f"CURRENT_PROJECT_VERSION = {self.current};",
                    'CURRENT_PROJECT_VERSION = "$(MARKETING_VERSION)";'))
                new = source.bump("patch", self.root)
                data = plistlib.loads((self.root / source.PLIST).read_bytes())
                self.assertEqual(data["CFBundleShortVersionString"], reference)
                self.assertEqual(data["CFBundleVersion"], reference)
                self.assertEqual(path.read_text().count('"$(MARKETING_VERSION)"'), 6)
                self.assertEqual(source.read(self.root), new)
        copy_source(self.root)
        self.plist(CFBundleVersion=self.current)
        new = source.bump("minor", self.root)
        self.assertEqual(plistlib.loads((self.root / source.PLIST).read_bytes())["CFBundleVersion"], new)

    def test_excluded_metadata_ignored(self):
        excluded = self.root / "Bookmark Manager.4dbase/Plugins/Bookmark Manager.bundle/Contents/Info.plist"
        excluded.parent.mkdir(parents=True)
        excluded.write_text("prebuilt 0.0.0")
        for name in ("manifest.json", "English.lproj/locversion.plist", "4D Plugin API/version.h"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("dependency/schema 16")
        source.bump("major", self.root)
        self.assertEqual(excluded.read_text(), "prebuilt 0.0.0")
        for name in ("manifest.json", "English.lproj/locversion.plist", "4D Plugin API/version.h"):
            self.assertEqual((self.root / name).read_text(), "dependency/schema 16")

    def test_localized_version_validation_and_bumping(self):
        path = self.root / source.LOCALIZED
        original = path.read_text()
        for malformed in (
            original.replace(f'CFBundleShortVersionString = "{self.current}"',
                             'CFBundleShortVersionString = "1.0"'),
            original.replace(f"Bookmark Manager version {self.current},",
                             "Bookmark Manager version invalid,"),
            original + f'\nCFBundleShortVersionString = "{self.current}";\n',
            original.replace("CFBundleShortVersionString", "UnknownKey"),
        ):
            with self.subTest(malformed=malformed):
                path.write_text(malformed)
                with self.assertRaises(ValueError):
                    source.read(self.root)
        path.write_text(original)
        new = source.bump("minor", self.root)
        self.assertIn(f'CFBundleShortVersionString = "{new}";', path.read_text())
        self.assertIn(f"Bookmark Manager version {new}, Copyright 2019 miyako.", path.read_text())
        self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))


class AvailabilityTests(unittest.TestCase):
    def test_paginated_draft_and_published_conflicts(self):
        for draft in (True, False):
            with self.subTest(draft=draft), patch.object(release, "remote_ref", return_value=None), \
                    patch.object(release, "api", side_effect=[
                        [entry()] * 100, [entry("v1.2.3", draft)]
                    ]) as api:
                with self.assertRaisesRegex(ValueError, "draft or published"):
                    release.available("owner/repo", "v1.2.3")
                self.assertEqual(api.call_args_list[1].args[0],
                                 "repos/owner/repo/releases?per_page=100&page=2")

    def test_only_complete_successful_no_match_is_absent(self):
        for pages in ([[]], [[entry()] * 100, []], [[entry()] * 100, [entry()]]):
            with patch.object(release, "remote_ref", return_value=None), \
                    patch.object(release, "api", side_effect=pages) as api:
                release.available("owner/repo", "v1.2.3")
                self.assertEqual(api.call_count, len(pages))

    def test_errors_on_every_page_fail_closed(self):
        for page in (1, 2):
            for error in (*(subprocess.CalledProcessError(1, ["gh", "api", str(status)])
                            for status in (401, 403, 404, 500)),
                          OSError("network"), json.JSONDecodeError("bad", "?", 0)):
                with self.subTest(page=page, error=error), \
                        patch.object(release, "remote_ref", return_value=None), \
                        patch.object(release, "api", side_effect=(
                            [[entry()] * 100] * (page - 1) + [error])):
                    with self.assertRaises((ValueError, OSError, subprocess.CalledProcessError)):
                        release.available("owner/repo", "v1.2.3")

    def test_malformed_page_and_entry_schema(self):
        bad_pages = [{}, None, "[]", [None], [{}], [dict(entry(), id=True)],
                     [dict(entry(), id=0)], [dict(entry(), tag_name=None)],
                     [dict(entry(), tag_name="")], [dict(entry(), draft="false")],
                     [dict(entry(), prerelease=None)], [entry()] * 101]
        for page in (1, 2):
            for bad in bad_pages:
                with self.subTest(page=page, bad=bad), \
                        patch.object(release, "remote_ref", return_value=None), \
                        patch.object(release, "api", side_effect=(
                            [[entry()] * 100] * (page - 1) + [bad])):
                    with self.assertRaises(ValueError):
                        release.available("owner/repo", "v1.2.3")

    def test_remote_tag_and_transport_failures(self):
        with patch.object(release, "remote_ref", return_value="a" * 40), \
                patch.object(release, "api") as api:
            with self.assertRaises(ValueError):
                release.available("o/r", "v1.2.3")
            api.assert_not_called()
        for output in ("not-a-sha\trefs/tags/v1.2.3", "a" * 40,
                       "a" * 40 + "\trefs/tags/wrong",
                       ("a" * 40 + "\trefs/tags/v1.2.3\n") * 2):
            with self.subTest(output=output), patch.object(release, "run", return_value=output):
                with self.assertRaises(ValueError):
                    release.remote_ref("refs/tags/v1.2.3")
        with patch.object(release, "run", side_effect=OSError("network")), \
                patch.object(release, "api") as api:
            with self.assertRaises(OSError):
                release.available("o/r", "v1.2.3")
            api.assert_not_called()

    def test_api_explicit_get_post_no_retry(self):
        with patch.object(release, "run", return_value="[]") as run:
            release.api("repos/o/r/releases?per_page=100&page=2")
            self.assertEqual(run.call_args.args,
                             ("gh", "api", "--method", "GET",
                              "repos/o/r/releases?per_page=100&page=2"))
        with patch.object(release, "run", return_value='{"id": 7}') as run:
            payload = {"tag_name": "v1.2.3", "draft": False}
            release.api("repos/o/r/releases", payload)
            self.assertIn("POST", run.call_args.args)
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
        with patch.object(release, "run", side_effect=subprocess.CalledProcessError(1, "gh")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                release.api("repos/o/r/releases")
            self.assertEqual(run.call_count, 1)
        with patch.object(release, "run", return_value='{"id": 8}') as run:
            asset = Path("Bookmark Manager-1.2.3.zip")
            endpoint = "https://uploads.github.com/repos/o/r/releases/123/assets?name=" + quote(asset.name)
            release.api(endpoint, asset=asset)
            self.assertEqual(run.call_args.args, (
                "gh", "api", "--method", "POST", endpoint,
                "--header", "Content-Type: application/octet-stream", "--input", str(asset)))


class GitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.local = self.root / "local"
        self.peer = self.root / "peer"
        git(self.root, "init", "--bare", str(self.remote))
        git(self.root, "init", "-b", "selected", str(self.local))
        for key, value in (("user.name", "Lifecycle Test"), ("user.email", "test@example.invalid"),
                           ("push.followTags", "true")):
            git(self.local, "config", key, value)
        git(self.local, "commit", "--allow-empty", "-m", "ancestor")
        self.ancestor = git(self.local, "rev-parse", "HEAD")
        copy_source(self.local)
        shutil.copytree(ROOT / ".github/scripts", self.local / ".github/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / ".gitignore", self.local / ".gitignore")
        git(self.local, "add", ".")
        git(self.local, "commit", "-m", "fixture")
        git(self.local, "remote", "add", "origin", str(self.remote))
        git(self.local, "push", "origin", "HEAD:refs/heads/selected")
        self.sha = git(self.local, "rev-parse", "HEAD")
        self.version = source.read(self.local)
        self.tag = f"v{self.version}"
        self.published = None
        self.uploaded = []
        git(self.root, "clone", "--branch", "selected", str(self.remote), str(self.peer))
        git(self.peer, "config", "user.name", "Peer")
        git(self.peer, "config", "user.email", "peer@example.invalid")
        self.enter = cwd(self.local)
        self.enter.__enter__()
        self.addCleanup(self.enter.__exit__, None, None, None)

    def advance_peer(self):
        (self.peer / "peer.txt").write_text("concurrent branch update")
        git(self.peer, "add", ".")
        git(self.peer, "commit", "-m", "peer")
        git(self.peer, "push", "origin", "HEAD:refs/heads/selected")

    def test_bump_selected_branch_no_tags_and_only_source_files(self):
        git(self.local, "tag", "-a", "unrelated-annotated", "-m", "must not follow")
        git(self.remote, "update-ref", "refs/heads/other", self.sha)
        release.bump_branch(self.sha, "selected", "patch")
        self.assertNotEqual(git(self.remote, "rev-parse", "refs/heads/selected"), self.sha)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/other"), self.sha)
        self.assertEqual(git(self.remote, "tag", "--list"), "")
        self.assertEqual(set(git(self.local, "diff-tree", "--no-commit-id", "--name-only",
                                 "-r", "HEAD").splitlines()), set(map(str, source.SOURCE_PATHS)))

    def test_bump_cli_bytecode_keeps_clean_checkout(self):
        env = os.environ.copy()
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        subprocess.run(
            [sys.executable, ".github/scripts/release.py", "bump", "--sha", self.sha,
             "--branch", "selected", "--mode", "patch"],
            env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(git(self.local, "status", "--porcelain"), "")
        self.assertNotEqual(git(self.remote, "rev-parse", "refs/heads/selected"), self.sha)
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_branch_race_before_preparation(self):
        self.advance_peer()
        with self.assertRaisesRegex(ValueError, "moved"):
            release.bump_branch(self.sha, "selected", "patch")
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), self.sha)

    def test_branch_race_during_preparation(self):
        real_bump = release.bump
        def concurrent_bump(mode):
            result = real_bump(mode)
            self.advance_peer()
            return result
        with patch.object(release, "bump", side_effect=concurrent_bump):
            with self.assertRaisesRegex(ValueError, "moved during"):
                release.bump_branch(self.sha, "selected", "minor")
        self.assertEqual(release.remote_ref("refs/heads/selected"),
                         git(self.peer, "rev-parse", "HEAD"))

    def advertised_race(self, kind):
        real_run = release.run
        expected = None
        events = []
        def concurrent_push(*args, **kwargs):
            nonlocal expected
            if "ls-remote" in args:
                events.append("ls-remote")
            if "push" in args:
                # Mutate after the helper's final ls-remote, before Git starts
                # receive-pack and receives its advertised refs.
                self.assertEqual(events, ["ls-remote", "ls-remote"])
                events.append("push")
                if kind == "rewind":
                    expected = self.ancestor
                    git(self.remote, "update-ref", "refs/heads/selected", expected)
                elif kind == "delete":
                    git(self.remote, "update-ref", "-d", "refs/heads/selected")
                elif kind == "advance":
                    self.advance_peer()
                    expected = git(self.peer, "rev-parse", "HEAD")
                elif kind == "same-result":
                    expected = git(self.local, "rev-parse", "HEAD")
                    git(self.remote, "fetch", "--no-tags", str(self.local), "HEAD")
                    git(self.remote, "update-ref", "refs/heads/selected", expected)
            return real_run(*args, **kwargs)
        with patch.object(release, "run", side_effect=concurrent_push):
            with self.assertRaises(subprocess.CalledProcessError):
                release.bump_branch(self.sha, "selected", "patch")
        self.assertEqual(events, ["ls-remote", "ls-remote", "push"])
        self.assertEqual(release.remote_ref("refs/heads/selected"), expected)
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_late_advertised_branch_rewind(self):
        self.advertised_race("rewind")

    def test_late_advertised_branch_deletion(self):
        self.advertised_race("delete")

    def test_late_advertised_branch_advance(self):
        self.advertised_race("advance")

    def test_late_advertised_same_result_race(self):
        self.advertised_race("same-result")

    def test_missing_or_nonexecutable_guard_fails_closed(self):
        guard = self.local / ".github/scripts/bump-hooks/pre-push"
        guard.chmod(0o644)
        for absent in (False, True):
            if absent:
                guard.unlink()
            with self.subTest(absent=absent), \
                    patch.object(release, "__file__", str(self.local / ".github/scripts/release.py")):
                with self.assertRaisesRegex(ValueError, "guard is missing or not executable"):
                    release.bump_branch(self.sha, "selected", "patch")
            self.assertEqual(git(self.local, "rev-parse", "HEAD"), self.sha)
            self.assertEqual(release.remote_ref("refs/heads/selected"), self.sha)

    def test_sha_branch_and_clean_source_validation(self):
        for sha in ("selected", "a" * 40, "a" * 39, "a" * 41):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                release.selected_sha(sha)
        release.selected_sha(self.sha)
        for branch in ("bad:branch", "selected~1", "", "selected..other"):
            with self.subTest(branch=branch), self.assertRaises(subprocess.CalledProcessError):
                release.bump_branch(self.sha, branch, "patch")
        path = self.local / source.LOCALIZED
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "clean"):
            release.bump_branch(self.sha, "selected", "patch")
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api") as api:
            with self.assertRaises(subprocess.CalledProcessError):
                release.preflight(self.sha)
            api.assert_not_called()

    def assets(self):
        paths = [Path(f"Bookmark Manager-{self.version}.{ext}") for ext in ("zip", "dmg")]
        for asset in paths:
            asset.write_bytes(b"fixture asset")
        return paths

    def publication_api(self, calls, fail=None, race=None):
        def api(endpoint, payload=None, asset=None):
            calls.append((endpoint, payload, asset))
            if "/releases?" in endpoint:
                return []
            if endpoint.endswith("/git/refs"):
                if race:
                    git(self.remote, "update-ref", f"refs/tags/{self.tag}", race)
                # Real atomic create-only bare Git models POST git/refs.
                git(self.remote, "update-ref", payload["ref"], payload["sha"], "0" * 40)
                return {"ref": payload["ref"], "object": {"sha": payload["sha"]}}
            if endpoint.endswith("/releases"):
                if fail == "release":
                    raise subprocess.CalledProcessError(1, ["gh", "api"])
                self.published = {"id": 123, "tag_name": self.tag, "draft": False, "prerelease": False}
                return self.published
            if asset is not None:
                if fail == asset.suffix:
                    raise subprocess.CalledProcessError(1, ["gh", "api"])
                self.uploaded.append(asset.name)
                return {"id": 456, "name": asset.name,
                        "size": asset.stat().st_size, "state": "uploaded"}
            raise AssertionError(endpoint)
        return api

    def test_create_only_exact_sha_and_new_release_id(self):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls)):
            release.publish(self.sha, self.assets())
        self.assertEqual(release.remote_ref(f"refs/tags/{self.tag}"), self.sha)
        self.assertIn("/releases?", calls[0][0])
        self.assertTrue(calls[1][0].endswith("/git/refs"))
        self.assertEqual(calls[2][1], {
            "tag_name": self.tag, "target_commitish": self.sha, "name": self.tag,
            "draft": False, "prerelease": False, "body": ""})
        self.assertEqual(len(calls), 5)
        for endpoint, payload, asset in calls[3:]:
            self.assertEqual(endpoint, "https://uploads.github.com/repos/owner/repo/"
                             "releases/123/assets?name=" + quote(asset.name))
            self.assertIsNone(payload)

    def test_tag_creation_races_same_and_different_sha(self):
        self.advance_peer()
        for race in (self.sha, git(self.peer, "rev-parse", "HEAD")):
            calls = []
            with self.subTest(race=race), patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                    patch.object(release, "api", side_effect=self.publication_api(calls, race=race)):
                with self.assertRaises(subprocess.CalledProcessError):
                    release.publish(self.sha, self.assets())
            self.assertEqual(len(calls), 2)
            self.assertEqual(release.remote_ref(f"refs/tags/{self.tag}"), race)
            # Fixture cleanup only, never production rollback.
            git(self.remote, "update-ref", "-d", f"refs/tags/{self.tag}")

    def test_release_post_and_each_upload_failure_retains_partial_state(self):
        for fail, count, uploaded in (("release", 3, []), (".zip", 4, []),
                                      (".dmg", 5, [f"Bookmark Manager-{self.version}.zip"])):
            calls = []
            self.published, self.uploaded = None, []
            with self.subTest(fail=fail), patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                    patch.object(release, "api", side_effect=self.publication_api(calls, fail=fail)):
                with self.assertRaises(subprocess.CalledProcessError):
                    release.publish(self.sha, self.assets())
            self.assertEqual(len(calls), count)
            self.assertEqual(release.remote_ref(f"refs/tags/{self.tag}"), self.sha)
            self.assertEqual(self.uploaded, uploaded)
            self.assertEqual(self.published is None, fail == "release")
            git(self.remote, "update-ref", "-d", f"refs/tags/{self.tag}")

    def test_final_recheck_blocks_new_draft(self):
        calls = []
        paths = self.assets()
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls)):
            release.preflight(self.sha)
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", return_value=[entry(self.tag, True)]) as api:
            with self.assertRaisesRegex(ValueError, "draft or published"):
                release.publish(self.sha, paths)
            self.assertEqual(api.call_count, 1)
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_remote_tag_verification_blocks_release(self):
        calls = []
        real_ref = release.remote_ref
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls)), \
                patch.object(release, "remote_ref", side_effect=lambda ref: "a" * 40 if real_ref(ref) else None):
            with self.assertRaisesRegex(ValueError, "exact-SHA verification"):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 2)
        self.assertIsNone(self.published)
        self.assertEqual(real_ref(f"refs/tags/{self.tag}"), self.sha)

    def test_malformed_post_responses_retain_accepted_state(self):
        for stage, count, uploaded in (("tag", 2, []), ("release", 3, []),
                                        ("asset", 4, [f"Bookmark Manager-{self.version}.zip"])):
            calls = []
            self.published, self.uploaded = None, []
            real_api = self.publication_api(calls)
            def malformed(endpoint, payload=None, asset=None):
                result = real_api(endpoint, payload, asset)
                if ((stage == "tag" and endpoint.endswith("/git/refs"))
                        or (stage == "release" and endpoint.endswith("/releases"))
                        or (stage == "asset" and asset is not None)):
                    return {"id": None}
                return result
            with self.subTest(stage=stage), patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                    patch.object(release, "api", side_effect=malformed):
                with self.assertRaises(ValueError):
                    release.publish(self.sha, self.assets())
            self.assertEqual(len(calls), count)
            self.assertEqual(release.remote_ref(f"refs/tags/{self.tag}"), self.sha)
            self.assertEqual(self.uploaded, uploaded)
            self.assertEqual(self.published is None, stage == "tag")
            git(self.remote, "update-ref", "-d", f"refs/tags/{self.tag}")

    def test_missing_or_wrong_assets_fail_before_remote_mutation(self):
        for paths in ([Path("wrong.zip")], [Path(f"Bookmark Manager-{self.version}.{ext}")
                                           for ext in ("zip", "dmg")]):
            with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                    patch.object(release, "api") as api:
                with self.assertRaises(ValueError):
                    release.publish(self.sha, paths)
                api.assert_not_called()
        self.assertEqual(git(self.remote, "tag", "--list"), "")


class WiringTests(unittest.TestCase):
    def test_manual_zero_input_immutable_gate_wiring(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertRegex(workflow, r"(?m)^name: Build$")
        self.assertEqual(workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0].strip(),
                         "workflow_dispatch:")
        self.assertEqual(workflow.count("uses: actions/checkout@v4"), 2)
        self.assertEqual(workflow.count("ref: ${{ github.sha }}"), 2)
        self.assertIn("group: release-publication\n  cancel-in-progress: false", workflow)
        self.assertNotIn("github.ref }}", workflow)
        self.assertIn("needs: [version]", workflow)
        self.assertEqual(workflow.count("GH_TOKEN: ${{ github.token }}"), 2)
        self.assertIn('test "$REF_TYPE" = branch', workflow)
        gates = [
            "preflight --sha", "import Developer ID certificate", "store notarytool credentials",
            "build macOS plugin (universal)", "verify universal binary", "- name: codesign",
            "package, notarize & staple", 'stapler staple "$DMG_PATH"',
            "recheck availability and create tag, release and assets", "publish --sha",
        ]
        positions = [workflow.index(gate) for gate in gates]
        self.assertEqual(positions, sorted(positions))
        for required in ('ARCHS="arm64 x86_64"', "ONLY_ACTIVE_ARCH=NO",
                         "codesign --verify --deep --strict", 'notarytool submit "$ZIP_PATH"',
                         'notarytool submit "$DMG_PATH"', "APPLE_DEVELOPER_ID_CERTIFICATE",
                         "APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD", "KEYCHAIN_PASSWORD",
                         "NOTARYTOOL_APPLE_ID", "NOTARYTOOL_TEAM_ID", "NOTARYTOOL_PASSWORD",
                         "PRODUCT_NAME: Bookmark Manager", "XCODE_PROJECT: Bookmark Manager.xcodeproj",
                         "MACOS_DEPLOYMENT_TARGET: '11.0'", "-configuration Default"):
            self.assertIn(required, workflow)
        for forbidden in ("continue-on-error", "always()", "softprops", "inputs.tag",
                          "build-windows", "VCX_SOLUTION", "cross-platform"):
            self.assertNotIn(forbidden, workflow)
        self.assertIn('needs.version.outputs.version', workflow)

    def test_bump_and_no_destructive_publication(self):
        workflow = (ROOT / ".github/workflows/bump-version.yml").read_text()
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("SELECTED_BRANCH: ${{ github.ref_name }}", workflow)
        self.assertIn('test "$REF_TYPE" = branch', workflow)
        for mode in ("patch", "minor", "major"):
            self.assertIn(f"- {mode}", workflow)
        self.assertNotIn("\n  push:", workflow)
        helper = (ROOT / ".github/scripts/release.py").read_text()
        for prohibited in ('"DELETE"', '"PATCH"', "--clobber", "--force",
                           '"gh", "release", "create"', '"git", "tag"'):
            self.assertNotIn(prohibited, helper)
        self.assertIn('"push.followTags=false"', helper)
        self.assertIn('"--no-follow-tags"', helper)
        self.assertIn('"core.hooksPath=', helper)
        self.assertNotIn("workflow_dispatch", helper)
        self.assertTrue(os.access(ROOT / ".github/scripts/bump-hooks/pre-push", os.X_OK))

    def test_publication_cli_accepts_assets_after_options(self):
        assets = [Path("Bookmark Manager-1.2.3.zip"), Path("Bookmark Manager-1.2.3.dmg")]
        with patch.object(sys, "argv", ["release.py", "publish", "--sha", "a" * 40,
                                       *map(str, assets)]), \
                patch.object(release, "publish") as publish:
            release.main()
        publish.assert_called_once_with("a" * 40, assets)


if __name__ == "__main__":
    unittest.main()
