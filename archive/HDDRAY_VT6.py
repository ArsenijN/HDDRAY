import os
import time
import configparser
import random
import subprocess
from ctypes import windll, WinError, create_string_buffer

SECTOR_SIZE = 512  # Define sector size for raw writes

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

def read_sector_and_repair(drive, sector, settings, logfile):
    """Read sector, attempt repair on failure, and log results."""
    max_try_count = settings['max_try_count']
    access_time_threshold = settings['access_time_threshold']
    cycle = 0

    for attempt in range(max_try_count):
        # Attempt to read the sector
        success, access_time = read_sector(sector)
        if success and access_time <= access_time_threshold:
            print(f"Sector {sector} read successfully in {access_time} ms.")
            logfile.write(f"{sector} | + | {attempt+1} | {max_try_count} | {access_time} | * | -\n")
            return True

        # Log read issue
        print(f"Sector {sector} read failed or slow (time: {access_time} ms), repairing...")
        pattern = "01010101" if cycle % 2 == 0 else "10101010"
        write_sector(sector, cycle)
        cycle += 1

    # If all attempts fail
    print(f"Sector {sector} is unrecoverable after {max_try_count} attempts.")
    logfile.write(f"{sector} | _ | {max_try_count} | {max_try_count} | - | . | RW\n")
    return False

def repair_mode(settings, drive):
    """Repair mode to process all sectors in a drive."""
    min_sector, max_sector = get_drive_range(drive)
    print(f"Repairing sectors from {min_sector} to {max_sector} on drive {drive}...")

    with open('list_of_recovered_sectors.txt', 'a') as logfile:
        for sector in range(min_sector, max_sector + 1):
            read_sector_and_repair(drive, sector, settings, logfile)

def main():
    print("Select mode:")
    print("1. Repair mode")
    choice = input("Enter your choice: ")

    if choice == '1':
        drive = select_drive()
        if drive:
            repair_mode(None, drive)
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()
