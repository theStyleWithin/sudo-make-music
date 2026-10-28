[app]
title = sudo make music
package.name = sudomakemusic
package.domain = io.github.thestylewithin
source.dir = .
source.include_exts = py,png,jpg,kv,svg
source.include_patterns = sudo_make_music/*.py,sudo_make_music/*/*.py
source.exclude_dirs = tests,docs,packaging,build,dist,.github
version = 0.1.0
requirements = python3,kivy,numpy
orientation = portrait
fullscreen = 0
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
