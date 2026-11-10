__version__ = "1.2.4"
version_info = tuple(int(i) for i in __version__.split("."))

# To refine the version with git info, a project's _version.py can do:
# try:
#     import sys
#     import alver
# except ImportError:
#     pass
# else:
#     __version__ = alver.get_detailed_version_of_lib(sys.modules[__name__]) or __version__
#     version_info = alver.get_version_tuple(__version__)
