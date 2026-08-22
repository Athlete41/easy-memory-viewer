"""
驱动服务加载/卸载工具（基于文件哈希匹配）
用法：
  安装: python driver.py install --path cracker.sys [--name Ckr] [--display "MyDrv"] [--desc "xxx"]
  卸载(按文件哈希): python driver.py uninstall --path cracker.sys
  卸载(按服务名):   python driver.py uninstall --name MyDrv
"""
import os, sys, ctypes, uuid, hashlib
import win32api, win32con, win32service, win32serviceutil, winerror, argparse

# ---------- 哈希计算 ----------
def calc_md5(file_path):
    """计算文件的MD5哈希值"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# ---------- 注册表操作 ----------
def write_reg_value(service_name, key_name, key_value):
    reg_path = f"SYSTEM\\CurrentControlSet\\Services\\{service_name}"
    key = win32api.RegOpenKey(win32con.HKEY_LOCAL_MACHINE, reg_path, 0, win32con.KEY_SET_VALUE)
    win32api.RegSetValueEx(key, key_name, 0, win32con.REG_SZ, key_value)
    win32api.RegCloseKey(key)

def read_reg_value(service_name, key_name):
    try:
        reg_path = f"SYSTEM\\CurrentControlSet\\Services\\{service_name}"
        key = win32api.RegOpenKey(win32con.HKEY_LOCAL_MACHINE, reg_path, 0, win32con.KEY_QUERY_VALUE)
        val, _ = win32api.RegQueryValueEx(key, key_name)
        win32api.RegCloseKey(key)
        return val
    except:
        return None

def find_services_by_hash(file_hash):
    """遍历所有服务，返回 FileHash 等于给定哈希的服务名列表"""
    found = []
    services_key = win32api.RegOpenKey(win32con.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Services", 0, win32con.KEY_READ)
    idx = 0
    while True:
        try:
            name = win32api.RegEnumKey(services_key, idx)
            if read_reg_value(name, "FileHash") == file_hash:
                found.append(name)
            idx += 1
        except:
            break
    win32api.RegCloseKey(services_key)
    return found

# ---------- 删除单个服务 ----------
def delete_service(service_name):
    try:
        win32serviceutil.StopService(service_name)
    except:
        pass
    try:
        win32serviceutil.RemoveService(service_name)
        print(f"  [√] 已删除 {service_name}")
        return True
    except win32api.error as e:
        print(f"  [×] 删除 {service_name} 失败: {e}")
        return False

# ---------- 安装 ----------
def install(driver_path, service_name=None, display_name=None, desc=""):
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("[-] 请以管理员身份运行")
        return False
    if not os.path.exists(driver_path):
        print(f"[-] 驱动文件不存在: {driver_path}")
        return False

    # 计算文件哈希
    file_hash = calc_md5(driver_path)
    print(f"[*] 驱动文件 MD5: {file_hash}")

    if not service_name:
        service_name = f"Ckr_{uuid.uuid4().hex[:6]}"
    if not display_name:
        display_name = service_name

    # 检查同名服务是否已存在
    try:
        win32serviceutil.QueryServiceStatus(service_name)
        print(f"[!] 服务 {service_name} 已存在，请先卸载")
        return False
    except win32api.error as e:
        if e.winerror != winerror.ERROR_SERVICE_DOES_NOT_EXIST:
            print(f"[-] 检查服务失败: {e}")
            return False

    h_scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    try:
        h_svc = win32service.CreateService(
            h_scm, service_name, display_name,
            win32service.SERVICE_ALL_ACCESS,
            win32service.SERVICE_KERNEL_DRIVER,
            win32service.SERVICE_DEMAND_START,
            win32service.SERVICE_ERROR_NORMAL,
            driver_path, None, False, None, None, None
        )
        if desc:
            win32service.ChangeServiceConfig2(h_svc, win32service.SERVICE_CONFIG_DESCRIPTION, desc)
        win32service.CloseServiceHandle(h_svc)
        # 写入哈希值到注册表（固定键名 FileHash）
        write_reg_value(service_name, "FileHash", file_hash)
        print(f"[+] 服务创建成功: {service_name}")
        print(f"    文件哈希已写入: FileHash = {file_hash}")
    except win32api.error as e:
        print(f"[-] 创建服务失败: {e}")
        win32service.CloseServiceHandle(h_scm)
        return False
    win32service.CloseServiceHandle(h_scm)

    try:
        win32serviceutil.StartService(service_name)
        print(f"[+] 服务启动成功")
    except win32api.error as e:
        if e.winerror != winerror.ERROR_SERVICE_ALREADY_RUNNING:
            print(f"[-] 启动服务失败: {e}")
            return False
        print("[!] 服务已在运行")
    return True

# ---------- 卸载（按文件哈希或按服务名） ----------
def uninstall(driver_path=None, service_name=None):
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("[-] 请以管理员身份运行")
        return False

    # 模式1：按服务名卸载
    if service_name:
        print(f"[*] 按服务名卸载: {service_name}")
        return delete_service(service_name)

    # 模式2：按文件哈希卸载（需要提供驱动路径）
    if driver_path:
        if not os.path.exists(driver_path):
            print(f"[-] 驱动文件不存在: {driver_path}")
            return False
        file_hash = calc_md5(driver_path)
        print(f"[*] 按文件哈希卸载: MD5 = {file_hash}")
        services = find_services_by_hash(file_hash)
        if not services:
            print(f"[!] 没有找到匹配该文件的服务")
            return True
        print(f"[*] 找到 {len(services)} 个服务: {', '.join(services)}")
        success = True
        for name in services:
            if not delete_service(name):
                success = False
        return success
    else:
        print("[-] 请指定 --path 或 --name")
        return False

# ---------- 命令行入口 ----------
def main():
    parser = argparse.ArgumentParser(description="驱动服务加载/卸载（基于文件哈希匹配）")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # install
    p_install = subparsers.add_parser("install", help="安装驱动")
    p_install.add_argument("--path", required=True, help="驱动文件路径")
    p_install.add_argument("--name", help="服务名（不指定则随机）")
    p_install.add_argument("--display", help="显示名（不指定则与服务名相同）")
    p_install.add_argument("--desc", help="服务描述", default="")

    # uninstall
    p_uninstall = subparsers.add_parser("uninstall", help="卸载驱动")
    p_uninstall.add_argument("--path", help="驱动文件路径（用于按哈希匹配卸载）")
    p_uninstall.add_argument("--name", help="按服务名卸载（指定此项则忽略 --path）")

    args = parser.parse_args()

    if args.action == "install":
        success = install(
            driver_path=args.path,
            service_name=args.name,
            display_name=args.display,
            desc=args.desc
        )
        sys.exit(0 if success else 1)
    else:  # uninstall
        # 如果指定了 --name，优先按名称卸载；否则按 --path 哈希卸载
        if args.name:
            success = uninstall(service_name=args.name)
        elif args.path:
            success = uninstall(driver_path=args.path)
        else:
            print("[-] 请指定 --path 或 --name")
            success = False
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()