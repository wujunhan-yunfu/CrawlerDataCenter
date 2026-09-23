"""CDC worker 入口: python -m backend.worker [--monitor]"""

from .tasks.worker import main

if __name__ == "__main__":
    main()