import os
import time
import configparser
import random
import subprocess
from ctypes import windll, WinError, create_string_buffer

SECTOR_SIZE = 512  # Define sector size for raw writes
settings_file = 'settings.ini'
recovered_sectors_file = 'list of recovered sectors.txt'

# Function to read settings from the ini file
def read_settings():
    config = configparser.ConfigParser()
    config.read(settings_file)
    settings = {
        'max_latency': int(config['DEFAULT']['max_latency']),
        'max_retries': int(config['DEFAULT']['max_retries'])
    }
    return settings

def list_raw_drives():
    """List all physical drives using PowerShell."""
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Get-CimInstance Win32_DiskDrive | Select-Object DeviceID,Model,Size"],
            capture_output=True,
            text=True,
        )
        drives = []
        for line in result.stdout.splitlines():
            if line.startswith("\\\\.\\PHYSICALDRIVE"):
                parts = line.split()
                if len(parts) >= 3:
                    device_id = parts[0]
                    model = " ".join(parts[1:-1])
                    size = int(parts[-1]) // (1024 ** 3)  # Convert bytes to GB
                    drives.append((device_id, model, size))
        return drives
    except Exception as e:
        print(f"Error listing drives: {e}")
        return []

def select_drive():
    """Prompt user to select a raw drive."""
    drives = list_raw_drives()
    if not drives:
        print("No drives found.")
        return None

    print("What drive to use:")
    for i, (device_id, model, size) in enumerate(drives, start=1):
        print(f"{i}. {model} ({size}GB) [{device_id}]")

    choice = int(input("Enter the drive number: ")) - 1
    if 0 <= choice < len(drives):
        return drives[choice][0]
    print("Invalid choice.")
    return None

def read_sector_raw(drive, sector):
    """Read a raw sector."""
    try:
        handle = windll.kernel32.CreateFileW(
            drive,  # Raw drive path
            0x80000000,  # GENERIC_READ
            0,  # No sharing
            None,
            3,  # OPEN_EXISTING
            0,
            None,
        )
        if handle == -1:
            raise WinError()

        buffer = create_string_buffer(SECTOR_SIZE)
        windll.kernel32.SetFilePointerEx(handle, sector * SECTOR_SIZE, None, 0)
        bytes_read = windll.kernel32.ReadFile(handle, buffer, SECTOR_SIZE, None, None)
        windll.kernel32.CloseHandle(handle)
        return bytes_read, buffer.raw
    except Exception as e:
        print(f"Error reading sector {sector}: {e}")
        return False, None

def write_sector_raw(drive, sector, pattern):
    """Write a raw sector with the specified pattern."""
    try:
        handle = windll.kernel32.CreateFileW(
            drive,  # Raw drive path
            0xC0000000,  # GENERIC_READ | GENERIC_WRITE
            0,  # No sharing
            None,
            3,  # OPEN_EXISTING
            0,
            None,
        )
        if handle == -1:
            raise WinError()

        buffer = create_string_buffer(pattern.encode('ascii') * (SECTOR_SIZE // len(pattern)))
        windll.kernel32.SetFilePointerEx(handle, sector * SECTOR_SIZE, None, 0)
        bytes_written = windll.kernel32.WriteFile(handle, buffer, SECTOR_SIZE, None, None)
        windll.kernel32.CloseHandle(handle)
        return bytes_written
    except Exception as e:
        print(f"Error writing sector {sector}: {e}")
        return False

def calibrate_latency(drive):
    """Calibrate latency by checking the first 8 sectors."""
    latencies = []
    for sector in range(8):
        start_time = time.time()
        success, _ = read_sector_raw(drive, sector)
        if success:
            latency = (time.time() - start_time) * 1000  # in milliseconds
            latencies.append(latency)
    if latencies:
        return sum(latencies) / len(latencies)
    return float('inf')

def repair_sector(settings, drive, sector, pattern_cycle):
    max_latency = settings['max_latency']
    max_retries = settings['max_retries']
    patterns = ["01010101", "10101010"]
    
    for attempt in range(max_retries):
        start_time = time.time()
        success, data = read_sector_raw(drive, sector)
        latency = (time.time() - start_time) * 1000  # in milliseconds

        if success and latency <= max_latency:
            return True, attempt + 1, latency, time.time() - start_time, "R"

        for pattern in patterns:
            write_sector_raw(drive, sector, pattern)

        success, data = read_sector_raw(drive, sector)
        if success:
            return True, attempt + 1, latency, time.time() - start_time, "RW"
        
    return False, max_retries, latency, time.time() - start_time, "-"

def repair_mode(settings, drive):
    min_sector, max_sector = 0, 100000  # Placeholder range
    print(f"Repairing sectors from {min_sector} to {max_sector} on drive {drive}...")
    pattern_cycle = 0

    for sector in range(min_sector, max_sector):
        is_good, attempts, latency, time_spent, error_type = repair_sector(settings, drive, sector, pattern_cycle)
        pattern_cycle += 1
        with open(recovered_sectors_file, 'a') as f:
            status = "+" if is_good else "-"
            f.write(f"{sector} | {status} | {attempts} | 8 | {latency if is_good else '-'} | {time_spent} | {error_type} | {'*' if is_good else '.'}\n")

def workout_mode(settings, drive):
    if not os.path.exists(recovered_sectors_file):
        print("No recovered sectors file found.")
        return

    print(f"Workout mode on drive {drive}...")

    with open(recovered_sectors_file, 'r') as f:
        for line in f:
            if line.strip().startswith("Legend"):
                continue
            parts = line.split("|")
            if len(parts) < 8:
                continue

            sector = int(parts[0].strip())
            status = parts[1].strip()
            if status == "+":
                repair_sector(settings, drive, sector, 0)

def main():
    settings = read_settings()

    print("Select mode:")
    print("1. Repair mode")
    print("2. Workout mode")
    choice = input("Enter your choice: ")

    if choice in ['1', '2']:
        drive = select_drive()
        if drive:
            if choice == '1':
                repair_mode(settings, drive)
            elif choice == '2':
                workout_mode(settings, drive)
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()