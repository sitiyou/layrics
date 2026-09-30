project('subproject-consumer')

# Pull the layrics repo in as a meson subproject and compile its overlay core
# into this project's own package under this project's own module name.
subproject('layrics', default_options: [
  'core_module_name=_overlay',
  'core_install_subdir=consumer',
])

py = import('python').find_installation('python3', pure: false)
install_subdir('consumer',
  install_dir : py.get_install_dir(),
  exclude_directories : ['__pycache__'],
  exclude_files : ['*.pyc'],
)
