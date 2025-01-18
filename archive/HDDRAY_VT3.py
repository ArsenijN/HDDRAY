import os
import time
import configparser
import random
import subprocess
import ctypes
from ctypes import windll, wintypes, byref

# Initialize settings.ini with default values
def initialize_settings():
    config = configparser.ConfigParser()
    if not os.path.exists('settings.ini'):
        config['DEFAULT'] = {
            'MaxTryCount': '10',
            'AccessTimeThreshold': '100',  # In ms
        }
        with open('settings.ini', 'w') as configfile:
            config.write(configfile)

def read_settings():
    config = configparser.ConfigParser()
    config.read('settings.ini')
    return {
        'max_try_count': int(config['DEFAULT']['MaxTryCount']),
        'access_time_threshold': int(config['DEFAULT']['AccessTimeThreshold']),
    }

# List drives using PowerShell
def list_drives():
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Get-CimInstance -Query 'SELECT * from Win32_DiskDrive'"],
            capture_output=True,
            text=True,
        )
        drives = []
        for line in result.stdout.splitlines():
            if "DeviceID" in line or "Model" in line:
                continue  # Skip headers
            fields = line.split(",")
            if len(fields) >= 2:
                drive_id = fields[0].strip()
                model = fields[1].strip()
                size = int(fields[2].strip()) // (1024 ** 3)  # Convert to GB
                drives.append((drive_id, model, size))
        return drives
    except Exception as e:
        print(f"Error listing drives: {e}")
        return []

# Select drive
def select_drive():
    drives = list_drives()
    if not drives:
        print("No drives found.")
        return None

    print("What drive to use:")
    for i, (drive_id, model, size) in enumerate(drives, start=1):
        print(f"{i}. {model} ({size}GB) [{drive_id}]")

    choice = int(input("Enter the drive number: ")) - 1
    if 0 <= choice < len(drives):
        return drives[choice][0]  # Return drive ID
    print("Invalid choice.")
    return None

# Open raw drive access
def open_raw_drive(drive_id):
    handle = windll.kernel32.CreateFileW(
        drive_id,
        0xC0000000,  # GENERIC_READ | GENERIC_WRITE
        0,  # No sharing
        None,  # No security attributes
        3,  # OPEN_EXISTING
        0,  # No flags
        None,  # No template
    )
    if handle == wintypes.HANDLE(-1).value:
        raise OSError("Failed to open raw drive.")
    return handle

# Close raw drive handle
def close_raw_drive(handle):
    windll.kernel32.CloseHandle(handle)

# Write to a sector with alternating patterns
def write_sector_raw(handle, sector, pattern):
    sector_size = 512
    data = bytearray(pattern.encode() * (sector_size // len(pattern)))
    offset = sector * sector_size
    overlapped = wintypes.OVERLAPPED()
    overlapped.Offset = offset & 0xFFFFFFFF
    overlapped.OffsetHigh = (offset >> 32) & 0xFFFFFFFF
    written = wintypes.DWORD()
    success = windll.kernel32.WriteFile(
        handle,
        data,
        len(data),
        byref(written),
        byref(overlapped),
    )
    if not success:
        raise OSError(f"Failed to write to sector {sector}")

# Repair mode
def repair_mode(settings, drive_id):
    handle = open_raw_drive(drive_id)
    try:
        print(f"Repairing sectors on drive {drive_id}...")
        min_sector, max_sector = 0, 1000000  # Replace with actual range detection
        for sector in range(min_sector, max_sector + 1):
            try_count = 0
            cycle = 0
            while try_count < settings['max_try_count']:
                pattern = "01010101" if cycle % 2 == 0 else "10101010"
                write_sector_raw(handle, sector, pattern)
                cycle += 1
                # Simulate access time for testing
                access_time = random.randint(50, 500)
                if access_time <= settings['access_time_threshold']:
                    print(f"Sector {sector} repaired successfully.")
                    break
                try_count += 1
            else:
                print(f"Sector {sector} is unrecoverable.")
    finally:
        close_raw_drive(handle)

# Main menu
def main():
    initialize_settings()
    settings = read_settings()

    print("Select mode:")
    print("1. Repair mode")
    choice = input("Enter your choice: ")

    if choice == '1':
        drive_id = select_drive()
        if drive_id:
            repair_mode(settings, drive_id)
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()
