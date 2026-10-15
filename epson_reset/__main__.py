import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Epson XP-530 waste-ink counter maintenance over Wi-Fi")
    parser.add_argument("--demo", action="store_true", help="use an in-memory printer; never access the network")
    parser.add_argument("--backup-dir", type=Path, help="override the local backup directory")
    args = parser.parse_args()
    from .gui import App

    App(demo=args.demo, backups=args.backup_dir).mainloop()


if __name__ == "__main__":
    main()
