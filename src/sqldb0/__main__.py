"""python3 -m sqldb0 入口:转发到 sqllogictest runner。"""

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
