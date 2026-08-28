[app]
title = Purivox
project_dir = .
input_file = deployment/main.py
exec_directory = dist
project_file = pyproject.toml
icon = src/resources/purivox.svg

[python]
python_path = /home/chouchiu/git/MR_Remover/.venv/bin/python
packages = Nuitka==4.1.3,ordered-set,zstandard
android_packages = 

[qt]
qml_files = 
excluded_qml_plugins = 
modules = Concurrent,Core,DBus,Gui,Multimedia,Network,Svg,Widgets
plugins = platforms,multimedia

[android]
wheel_pyside = 
wheel_shiboken = 
plugins = 

[nuitka]
macos.permissions = 
mode = onefile
extra_args = --quiet --assume-yes-for-downloads --noinclude-qt-translations --include-package=app --include-package=entrypoints --include-package=features --include-package=resources --include-package-data=resources --include-package=shared --include-package=qfluentwidgets --include-package=scipy._external.array_api_compat.numpy --include-module=onnxruntime.capi._pybind_state

[buildozer]
mode = debug
recipe_dir = 
jars_dir = 
ndk_path = 
sdk_path = 
local_libs = 
arch = 

