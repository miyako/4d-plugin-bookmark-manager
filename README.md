4d-plugin-bookmark-manager
==========================

This plugin allows access to Finder aliases (a.k.a bookmarks).

In particular, you can convert a bookmark file to BLOB, create a bookmark from that BLOB, or retrieve the path associated to that bookmark.

c.f. [Locating Files Using Bookmarks](https://developer.apple.com/library/mac/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/AccessingFilesandDirectories/AccessingFilesandDirectories.html#//apple_ref/doc/uid/TP40010672-CH3-SW10)

similar project [4d-plugin-alias-manager](https://github.com/miyako/4d-plugin-alias-manager)

### Platform

| carbon | cocoa | win32 | win64 |
|:------:|:-----:|:---------:|:---------:|
|<img src="https://cloud.githubusercontent.com/assets/1725068/22371562/1b091f0a-e4db-11e6-8458-8653954a7cce.png" width="24" height="24" />|<img src="https://cloud.githubusercontent.com/assets/1725068/22371562/1b091f0a-e4db-11e6-8458-8653954a7cce.png" width="24" height="24" />|||

### Version

<img src="https://cloud.githubusercontent.com/assets/1725068/18940649/21945000-8645-11e6-86ed-4a0f800e5a73.png" width="32" height="32" /> <img src="https://cloud.githubusercontent.com/assets/1725068/18940648/2192ddba-8645-11e6-864d-6d5692d55717.png" width="32" height="32" /> <img src="https://user-images.githubusercontent.com/1725068/41266195-ddf767b2-6e30-11e8-9d6b-2adf6a9f57a5.png" width="32" height="32" />

![preemption xx](https://user-images.githubusercontent.com/1725068/41327179-4e839948-6efd-11e8-982b-a670d511e04f.png)

### Releases

[2.0](https://github.com/miyako/4d-plugin-bookmark-manager/releases/tag/2.0)

### Examples

```
$path:=Structure file

$bookmark:=BOOKMARK Create ($path)
$info:=BOOKMARK Resolve ($bookmark)

$dest:=System folder(Desktop)+"test"
$error:=BOOKMARK Export to file ($bookmark;$dest)
```
