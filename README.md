# 4d-plugin-bookmark-manager

Bookmark Manager gives 4D access to macOS Finder aliases (technically "bookmarks"): you can turn a file's location into a portable `BLOB` that survives the file being moved or renamed, recreate that `BLOB` later, and resolve it back to a path — the same mechanism Finder itself uses for aliases, backed by Foundation's `NSURL` bookmark APIs.

Command | Returns | Purpose
--------|---------|--------
[`BOOKMARK Create`](#bookmark-create) | Blob | Create bookmark data for a file or folder at a given path.
[`BOOKMARK Resolve`](#bookmark-resolve) | Text | Resolve bookmark data back to a POSIX path.
[`BOOKMARK Export to file`](#bookmark-export-to-file) | Longint | Write bookmark data out as a `.alias`/bookmark file on disk.

**Platforms:** macOS (Carbon and Cocoa builds) only. There is no Windows implementation — bookmark data is a macOS/Foundation-specific mechanism with no Windows equivalent, so this isn't a partial port, it's the plugin's complete, intended scope.

## Manual versioning and publication

In Actions, select **Bump version**, explicitly select the source branch in
**Run workflow**, and choose `patch`, `minor`, or `major`. It validates the
immutable dispatch SHA, clean checkout, branch ref and coordinated source
metadata, then commits only the source version files to that branch. It creates
no tag and triggers no Build. Both remote checks and a mandatory executable
pre-push guard require the advertised old branch SHA to equal the selected SHA;
late advances, ancestor rewinds, deletions and same-result races fail closed.
The push is nonforce and disables tag following even if `push.followTags=true`.
Branch protection failures require operator action, not a bypass.

Run **Build** separately on the intended branch/commit. It has no inputs, accepts
no typed tag and never runs on a push or pull request. Every checkout uses the
selected `github.sha`. Its source-derived strict `X.Y.Z` becomes `vX.Y.Z` only
after the existing macOS universal (`arm64` + `x86_64`) build, architecture check,
Developer ID signing/verification, ZIP and DMG notarization, and DMG stapling.
The existing Xcode build phases and native dependencies are unchanged. Outputs
remain `Bookmark Manager-X.Y.Z.zip` and `Bookmark Manager-X.Y.Z.dmg`; this is not
a Windows build. Existing signing/notary secret names remain unchanged.

`MARKETING_VERSION` is the authority across six target/project configurations.
History introduced it and `CURRENT_PROJECT_VERSION` together at `2.2.0`
(`dd6c1bb`); the old bump header promised both, but `34ce39c` and `e3250b2`
advanced only marketing and the source plist. Thus current-project is a stale
coordinated value, not an independent build counter. This migration aligns it
and the stale English source overrides to the existing **2.2.2**, without a
release increment. Future bumps validate and update all three source files:
`Bookmark Manager.xcodeproj/project.pbxproj`, `Info.plist`, and
`English.lproj/InfoPlist.strings`. Valid version-setting references are retained;
the absent `CFBundleVersion` stays absent. Prebuilt bundle metadata, 4D data,
manifest/schema versions and bundled 4D Plugin API dependencies are not inputs
and are never rewritten.

Builds share one repository-wide, cross-branch publication concurrency group.
Before native work and again immediately after all gates, authenticated
paginated release listing (including drafts) and remote tag checks must both
succeed without a match. API 404, permission, network, malformed-response and
later-page failures are errors, never evidence of absence. Publication uses
create-only tag creation at the selected SHA and verifies the remote SHA.
It then POSTs a new non-draft, non-prerelease release with the tag as its name,
the exact SHA as `target_commitish`, and empty notes (no generated notes).
Separate asset POSTs target only the newly returned release ID.

**Partial publication and recovery:** creation/upload errors stop immediately.
There is no delete, update, clobber, rollback or automatic retry; any created
tag, release and accepted assets remain for inspection, even after an ambiguous
API/network response. Do not rerun expecting an overwrite: existing tags or
draft/published releases block it. Inspect the Actions log, exact remote tag
SHA, release ID and accepted asset names manually. An operator must decide how
to complete a verified partial release outside this create-only workflow, or
use a separately reviewed source bump and a new Build for a new version.
Never move an existing release tag to a different commit.

Local lifecycle checks (no native build, credentials or publication required):

```sh
python3 -m unittest discover -s .github/tests -v
actionlint
```

## Native ownership regression

The compiled, currently command-dormant `CPicture` helper uses owning string
and picture arguments for synchronous 4D commands. A path string is released
only by its argument, the picture output is cleared after the wrapper retains
it, and `setBytes` releases its temporary creation reference after retention.
Arguments immediately assigned a string or picture start Undefined rather
than allocating an empty owner that would be overwritten. Charset conversion
returns **bytes**, which are divided by `sizeof(PA_Unichar)` before building
a UTF-16 string. Returned picture handoffs remain owned by their callers.

On macOS with Xcode command-line tools, run:

```sh
python3 .github/tests/run_native_ownership.py --baseline
python3 .github/tests/run_native_ownership.py
```

Both use the same test harness, actual dispatcher, all 16 class implementations,
and the **complete unchanged bundled SDK**. The baseline command extracts only
native sources at immutable `ec7ef9b405e4d2e9de06701e0bff18816ca9e76b`
into a temporary directory, and requires six named failures: path
double-disposal, temporary-picture/empty-argument leaks, and `createCopy`'s
ASan heap-buffer-overread. The fixed command requires 88 passing combinations:
11 cases across allocated/null empty representations, command success/no-op
failure, and in-place/replaced pictures. ASan/UBSan stay enabled; macOS LSan
is not used, so each process explicitly requires zero live tracked strings,
handles and picture references.

The synthetic engine-boundary shim preserves byte capacities, UTF-16 unit
counts, terminator boundaries and reference ownership. Fixtures cover exact
ASCII, BMP, supplementary and empty text; independent array/callback owners;
borrowed copies surviving replacement/clear; accepted transfers, replacement,
growth/shrink and rejection by type/data/index/null descriptor; and picture
handoffs surviving wrapper destruction. The unsigned **Native ownership** CI
job runs these checks and the lifecycle suite only. It never invokes an Xcode
target, signing, notarization, packaging or publication. Both existing release
workflows remain manual-only and unchanged.

Audit scope includes `4DPlugin.cpp/.h`, both manifests (three matching scalar
commands, dispatcher cases 1-3), the prefix header, every `Classes/*.cpp/.h`,
and both projects' compile/include surfaces. Both projects compile all class
implementations plus `4DPluginAPI.c`; the API header includes the wrappers.
`C_TEXT` copies borrowed inputs into C++ storage and uses the content setter
for outputs; `ARRAY_TEXT` makes a separate allocation per accepted array
transfer. No exported text-array command, JSON Parse/ExecuteCommand helper,
object/collection getter API or additional native/third-party implementation
is present. Scalar, BLOB, pointer and other array wrappers were included in
the inventory, not excluded because the manifest has no arrays.

SDK provenance is the repository's bundled file, last changed at
`dd6c1bb48a4f7e8e7b4aff0314db154a7a96fd50`, SHA-256
`355ee208ad6c61dcc68e8432546fc42484888211dd07ed8fa3fdb4440f3edbd8`
(`4DPluginAPI.c`). Its v14 source/v13 header comments are not verified upstream
release identities. The audit follows the canonical native ownership skill
at `miyako/skills` revision `e6b492fcb81e5e1a7f7db723594b420e63bf6eb9`
(merged guidance from PRs 69 and 71).

**Limits and deferred evidence:** the shim is not execution in 4D or Windows
and does not certify bookmark behavior or the originating Poppler crash.
`C_POINTER::getVariable` interprets a `PA_GetPointerValue` result as reference
metadata despite a header cleanup comment; its ownership is ambiguous and was
not changed. Successful SDK picture-data/application-path output ownership is
also not established by the bundled forwarding code; the shim models no
picture representations, checks the error before consuming a returned value,
and deliberately does not infer a disposal rule. SDK array resize allocation
failure can corrupt the reported count independently of these changes:
normal resize tests do not certify OOM behavior, and no SDK rewrite is included.
The five picture commands are procedures; their ignored result is modeled as
Undefined, not as evidence about owning results from arbitrary other commands.

---

## Requirements & platform notes

- All three commands take their parameters unconditionally — there is no optional-parameter form for any of them; omitting a parameter is not supported.
- All three commands are declared thread-safe in the plugin's manifest, so they may run on any of 4D's worker threads, not just the main process/UI thread.
- **Failure is silent, not a 4D error.** None of these commands raise an error via `Method called on error`/4D's error-handling mechanism. A failure (bad path, corrupted or stale bookmark data, an unreadable destination) instead comes back as an **empty result** (`BOOKMARK Create`/`BOOKMARK Resolve`) or a **non-zero result code** (`BOOKMARK Export to file`). Always check the returned value rather than assuming success.
- Bookmark data returned by `BOOKMARK Create` is meant to be treated as an opaque `BLOB` — store it, pass it to `BOOKMARK Resolve`/`BOOKMARK Export to file` later, but don't rely on its internal byte layout.

---

## BOOKMARK Create

### Syntax

```
BOOKMARK Create ( path ) → bookmarkData
```

Parameter | Type | Description
----------|------|------------
`path` | Text | POSIX path of the file or folder to bookmark.
Result | Blob | Bookmark data for `path`, or an empty `BLOB` if the path couldn't be resolved or bookmark creation failed.

### Description

`BOOKMARK Create` resolves `path` to a file-system location and asks Foundation to build bookmark data for it (`NSURL bookmarkDataWithOptions:includingResourceValuesForKeys:relativeToURL:error:`), including a broad set of resource properties (name, type identifier, file size, creation/modification dates, hidden/package/immutable flags, and others) so the bookmark can be resolved robustly later even if the file has since moved.

If `path` doesn't resolve to a real location, or Foundation can't build bookmark data for it (e.g. insufficient permissions, path is on a volume that doesn't support bookmarks), the command returns an **empty `BLOB`** — check the length of the result before using it.

Bookmark creation is a Finder-alias-style operation: as long as the underlying file or folder still exists somewhere reachable (even under a different name, in a different folder, or after the volume was renamed), a bookmark created from it can typically still be resolved back to its new location by `BOOKMARK Resolve`.

### Example

From the plugin's own README example:

```4d
$path:=Structure file
$bookmark:=BOOKMARK Create ($path)
```

Guarding against a failed creation:

```4d
$bookmark:=BOOKMARK Create ($path)
If (BLOB size($bookmark)=0)
	ALERT ("Could not create a bookmark for: "+$path)
End if
```

---

## BOOKMARK Resolve

### Syntax

```
BOOKMARK Resolve ( bookmarkData ) → path
```

Parameter | Type | Description
----------|------|------------
`bookmarkData` | Blob | Bookmark data previously returned by [`BOOKMARK Create`](#bookmark-create).
Result | Text | POSIX path (slash-delimited) the bookmark currently resolves to, or an empty string if resolution failed.

### Description

`BOOKMARK Resolve` rebuilds an `NSURL` from `bookmarkData` (`initByResolvingBookmarkData:options:relativeToURL:bookmarkDataIsStale:error:`) and returns its file-system path as a **POSIX-style path** (forward-slash-delimited, e.g. `/Users/name/file.txt`) — the same path style 4D's own file commands use.

If `bookmarkData` is empty, corrupted, or no longer resolves to any location on disk, the command returns an **empty Text** value — check for an empty string rather than assuming the bookmark is always resolvable.

The resolution is done without any UI prompt (equivalent to Foundation's "without UI" resolution option), so it will never pop a system dialog asking the user to locate a missing file — a bookmark that can't be silently resolved simply comes back empty.

> **Note:** This command returns a POSIX-style path as of the current source. An earlier revision of this plugin returned a legacy, colon-delimited HFS-style path (e.g. `Macintosh HD:Users:name:file.txt`) instead, which is not directly usable by most 4D file commands — if you're working from an older compiled build of this plugin rather than a rebuild of the current source, confirm which path style you're actually getting back before relying on it downstream.

### Example

From the plugin's own README example:

```4d
$info:=BOOKMARK Resolve ($bookmark)
```

Guarding against a bookmark that no longer resolves:

```4d
$path:=BOOKMARK Resolve ($bookmark)
If ($path="")
	ALERT ("Bookmark could not be resolved — the file may have been deleted.")
Else
	ALERT ("Current location: "+$path)
End if
```

---

## BOOKMARK Export to file

### Syntax

```
BOOKMARK Export to file ( bookmarkData ; destinationPath ) → errorCode
```

Parameter | Type | Description
----------|------|------------
`bookmarkData` | Blob | Bookmark data previously returned by [`BOOKMARK Create`](#bookmark-create).
`destinationPath` | Text | POSIX path to write the bookmark/alias file to.
Result | Longint | `0` on success. Non-zero on failure — see below.

### Description

`BOOKMARK Export to file` writes `bookmarkData` out to `destinationPath` as a standalone bookmark file (`NSURL writeBookmarkData:toURL:options:error:`), suitable for later re-reading as a `.alias`-style file. This is a separate step from creating the bookmark data itself — call [`BOOKMARK Create`](#bookmark-create) first to get `bookmarkData`.

The result code distinguishes two failure shapes:

- If `destinationPath` doesn't resolve to a writable location at all, the command returns the fixed constant **`NSFileNoSuchFileError`** (from Foundation's `NSCocoaErrorDomain`) without attempting the write.
- If the location resolves but the write itself fails (permissions, disk full, unsupported volume, etc.), the command returns whatever error code Foundation's `writeBookmarkData:toURL:options:error:` produced for that failure — treat any non-zero result as failure and, if you need to distinguish specific causes, cross-reference the code against Apple's `NSCocoaErrorDomain` documentation.

A result of `0` means the file was written successfully.

### Example

From the plugin's own README example:

```4d
$dest:=System folder(Desktop)+"test"
$error:=BOOKMARK Export to file ($bookmark;$dest)
```

Checking the result:

```4d
$error:=BOOKMARK Export to file ($bookmark;$dest)
If ($error#0)
	ALERT ("Export failed with error code: "+String($error))
End if
```

---

## Error handling & troubleshooting

- **Empty result means failure, not a raised 4D error.** [`BOOKMARK Create`](#bookmark-create) and [`BOOKMARK Resolve`](#bookmark-resolve) signal failure by returning an empty `BLOB`/`Text` rather than triggering 4D's error-handling mechanism — always check the size/content of the result.
- **A non-zero result from [`BOOKMARK Export to file`](#bookmark-export-to-file) is the only place this plugin surfaces an explicit numeric error code** — `0` is success, anything else (including the fixed `NSFileNoSuchFileError` constant for an unresolvable destination) is failure.
- **No UI prompts on a missing file.** [`BOOKMARK Resolve`](#bookmark-resolve) resolves bookmarks silently; it will never show the user a "locate this file" dialog. Design your own fallback (re-prompt the user to pick a new location, fall back to a stored path, etc.) around an empty result.
- **A stale-but-resolvable bookmark is still resolved successfully.** If the bookmarked file has moved, `BOOKMARK Resolve` still returns its current path rather than failing — this plugin doesn't currently expose Foundation's "is this bookmark stale" flag, so you won't be told the file moved, only where it is now.
- **Bookmark data isn't portable across machines/volumes in the general case.** Like a Finder alias, a bookmark is tied to the specific volume/file it was created from; moving the referenced file to a different disk or another machine can make it unresolvable even though the bytes themselves are intact.
- macOS only — there is no Windows build of this plugin to fall back to.

---

## Quick reference

```4d
 // Create a bookmark, resolve it, and export it to a file
$path:=Structure file
$bookmark:=BOOKMARK Create ($path)

If (BLOB size($bookmark)>0)
	
	$current:=BOOKMARK Resolve ($bookmark)
	
	$dest:=System folder(Desktop)+"test"
	$error:=BOOKMARK Export to file ($bookmark;$dest)
	
	If ($error=0)
		 // bookmark file written to $dest
	End if
	
End if
```
