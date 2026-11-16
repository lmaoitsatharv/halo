import sys

if __name__ == "__main__" and sys.argv[1:2] == ["--apply-update"]:
    # The update helper runs from a new version's staged copy, before (and without) Qt.
    from halo.update_helper import main as apply_update
    raise SystemExit(apply_update())

from halo.app import main

if __name__ == "__main__":
    raise SystemExit(main())
