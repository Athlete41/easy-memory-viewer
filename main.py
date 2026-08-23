import sys
import os
import zipfile

from pathlib import Path
from PySide6.QtWidgets import QApplication
from ui.main_window import EasyMemoryViewerWindow
from core.cracker_installer import install, uninstall


def main() -> int:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cracker_path = os.path.join(current_dir, "driver", "cracker.sys")
    if not os.path.exists(cracker_path):
        cracker_zip_path = os.path.join(current_dir, "driver", "cracker.zip")
        if os.path.exists(cracker_zip_path):
            with zipfile.ZipFile(cracker_zip_path, 'r') as zf:
                zf.extractall(os.path.join(current_dir, "driver"))
        else:
            print("驱动不存在")
            sys.exit(1)

    uninstall(cracker_path)
    if not install(cracker_path, desc="为用户提供某种特殊服务"):
        print("安装失败")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("EasyMemoryViewer")
    app.setOrganizationName("EasyMemoryViewer")

    # qss_path = Path(__file__).parent / "resources" / "style.qss"
    # if qss_path.exists():
    #     app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    window = EasyMemoryViewerWindow()
    window.resize(1280, 860)
    window.show()
    status = app.exec()
    uninstall(cracker_path)
    return status

if __name__ == "__main__":
    sys.exit(main())