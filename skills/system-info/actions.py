import platform
from typing import Dict

try:
    import psutil
except ImportError:
    psutil = None


def get_system_info(params: Dict) -> str:
    """Get CPU, memory, and OS information."""
    if not psutil:
        return "Error: psutil not installed"

    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()
    mem = psutil.virtual_memory()
    boot = psutil.boot_time()

    import datetime
    uptime = datetime.datetime.now() - datetime.datetime.fromtimestamp(boot)
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes = remainder // 60

    return (
        f"**System Information**\n"
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})\n"
        f"Python: {platform.python_version()}\n"
        f"CPU: {cpu_count} cores, {cpu_percent}% usage\n"
        f"Memory: {mem.used / (1024**3):.1f} GB / {mem.total / (1024**3):.1f} GB ({mem.percent}% used)\n"
        f"Uptime: {hours}h {minutes}m"
    )


def get_disk_usage(params: Dict) -> str:
    """Get disk usage for all mounted partitions."""
    if not psutil:
        return "Error: psutil not installed"

    lines = ["**Disk Usage:**"]
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            total_gb = usage.total / (1024**3)
            used_gb = usage.used / (1024**3)
            free_gb = usage.free / (1024**3)
            lines.append(
                f"- {part.mountpoint} ({part.fstype}): "
                f"{used_gb:.1f} GB / {total_gb:.1f} GB used ({usage.percent}%), "
                f"{free_gb:.1f} GB free"
            )
        except PermissionError:
            continue

    return "\n".join(lines) if len(lines) > 1 else "No accessible partitions found."


def list_processes(params: Dict) -> str:
    """List top processes by CPU or memory usage."""
    if not psutil:
        return "Error: psutil not installed"

    sort_by = params.get("sort_by", "cpu").lower()
    limit = int(params.get("limit", "10"))
    key = "cpu_percent" if sort_by == "cpu" else "memory_percent"

    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            procs.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    procs.sort(key=lambda x: x.get(key, 0), reverse=True)
    top = procs[:limit]

    lines = [f"**Top {limit} Processes (by {sort_by}):**"]
    for p in top:
        lines.append(
            f"- PID {p['pid']}: {p['name']} — CPU {p.get('cpu_percent', 0):.1f}%, "
            f"Mem {p.get('memory_percent', 0):.1f}%"
        )

    return "\n".join(lines)


def get_network_info(params: Dict) -> str:
    """Get network interface information."""
    if not psutil:
        return "Error: psutil not installed"

    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    lines = ["**Network Interfaces:**"]
    for iface, addr_list in addrs.items():
        stat = stats.get(iface)
        status = "up" if stat and stat.isup else "down"
        ipv4 = next((a.address for a in addr_list if a.family.name == "AF_INET"), None)
        if ipv4:
            lines.append(f"- {iface}: {ipv4} ({status})")

    return "\n".join(lines) if len(lines) > 1 else "No network interfaces found."
