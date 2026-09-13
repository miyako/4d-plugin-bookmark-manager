# 4d-plugin-bookmark-manager

Bookmark Manager gives 4D access to macOS Finder aliases (technically "bookmarks"): you can turn a file's location into a portable `BLOB` that survives the file being moved or renamed, recreate that `BLOB` later, and resolve it back to a path — the same mechanism Finder itself uses for aliases, backed by Foundation's `NSURL` bookmark APIs.

Command | Returns | Purpose
--------|---------|--------
[`BOOKMARK Create`](#bookmark-create) | Blob | Create bookmark data for a file or folder at a given path.
[`BOOKMARK Resolve`](#bookmark-resolve) | Text | Resolve bookmark data back to a POSIX path.
[`BOOKMARK Export to file`](#bookmark-export-to-file) | Longint | Write bookmark data out as a `.alias`/bookmark file on disk.

**Platforms:** macOS (Carbon and Cocoa builds) only. There is no Windows implementation — bookmark data is a macOS/Foundation-specific mechanism with no Windows equivalent, so this isn't a partial port, it's the plugin's complete, intended scope.

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
