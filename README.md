4d-plugin-bookmark-manager
==========================

This plugin allows access to Finder aliases (a.k.a bookmarks).

In particular, you can convert a bookmark file to BLOB, create a bookmark from that BLOB, or retrieve the path associated to that bookmark.

c.f. [Locating Files Using Bookmarks](https://developer.apple.com/library/mac/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/AccessingFilesandDirectories/AccessingFilesandDirectories.html#//apple_ref/doc/uid/TP40010672-CH3-SW10)

##Platform

| carbon | cocoa | win32 | win64 |
|:------:|:-----:|:---------:|:---------:|
|🆗|🆗|🚫|🚫|

##Commands

```c
// --- Bookmarks
BOOKMARK Create
BOOKMARK Resolve
BOOKMARK Export_to_file
```

##Examples

```
$path:=Structure file

$bookmark:=BOOKMARK Create ($path)
$info:=BOOKMARK Resolve ($bookmark)

$dest:=System folder(Desktop)+"test"
$error:=BOOKMARK Export to file ($bookmark;$dest)
```
