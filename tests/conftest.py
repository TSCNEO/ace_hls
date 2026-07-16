import os
import tempfile


# Service singletons are imported while pytest collects tests. Keep their
# persistent paths writable without requiring Docker or shell environment setup.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ace-hls-pytest-"))
os.environ.setdefault("URL_ORIGEN", "")
