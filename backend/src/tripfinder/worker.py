"""Worker process entrypoint. Phase 0: proves the process boots; no job logic yet."""

import time


def main() -> None:
    while True:
        print("worker heartbeat")
        time.sleep(5)


if __name__ == "__main__":
    main()
