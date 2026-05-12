# archive-editor-git (AUR)

This package installs ArchiveEditor as a native Arch Linux application.

## Build locally

```bash
makepkg -si
```

## Publish to AUR

```bash
git clone ssh://aur@aur.archlinux.org/archive-editor-git.git
cd archive-editor-git
```

Copy:
- PKGBUILD
- .SRCINFO

Then:

```bash
makepkg --printsrcinfo > .SRCINFO
git add .
git commit -m "Initial AUR release"
git push
```
