[app]
title = sudo make music
package.name = sudomakemusic
package.domain = io.github.thestylewithin
source.dir = .
source.include_exts = py,png,jpg,kv,svg
source.include_patterns = sudo_make_music/*.py,sudo_make_music/*/*.py
source.exclude_dirs = tests,docs,packaging,build,dist,.github
version = 1.0.0
requirements = python3,kivy,numpy,pyjnius
orientation = portrait
fullscreen = 0
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
# Not enabled in 1.0: on-device Stable Audio needs the LiteRT gradle dependency (com.google.ai.edge.litert:litert,
# version to be verified) once converted models + sentencepiece exist. See docs/STABLE_AUDIO_LITERT.md.
# android.gradle_dependencies = com.google.ai.edge.litert:litert:<version>
android.accept_sdk_license = True

# Pin python-for-android to a known-good release: its master moved to Python 3.14 and pip then rejects
# the android wheels of pure-python dependencies ("charset_normalizer ... not a supported wheel").
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
