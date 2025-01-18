import os
import time
import configparser
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
        'max_latency': int(config['DEFAULT'].get('max_latency', 100)),
        'max_retries': int(config['DEFAULT'].get('max_retries', 8)),
        'max_repair_latency': int(config['DEFAULT'].get('max_repair_latency', 50)),
        'min_sector': int(config['DEFAULT'].get('min_sector', 0)),
        'max_sector': int(config['DEFAULT'].get('max_sector', 0)),
        'regenerator_reads': int(config['DEFAULT'].get('regenerator_reads', 32)),
        'f1_sector_write': int(config['DEFAULT'].get('f1_sector_write', 3)),
        'f1_sector_read': int(config['DEFAULT'].get('f1_sector_read', 5)),
        'f1_sector_attempts': int(config['DEFAULT'].get('f1_sector_attempts', 3)),
        'repair_sector_write': int(config['DEFAULT'].get('repair_sector_write', 3)),
        'repair_sector_read': int(config['DEFAULT'].get('repair_sector_read', 5)),
        'repair_sector_attempts': int(config['DEFAULT'].get('repair_sector_attempts', 3)),
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
    except WinError as e:
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

        buffer = create_string_buffer(pattern * (SECTOR_SIZE // len(pattern)))
        windll.kernel32.SetFilePointerEx(handle, sector * SECTOR_SIZE, None, 0)
        bytes_written = windll.kernel32.WriteFile(handle, buffer, SECTOR_SIZE, None, None)
        windll.kernel32.CloseHandle(handle)
        return bytes_written
    except Exception as e:
        print(f"Error writing sector {sector}: {e}")
        return False

def verify_sector(drive, sector, pattern):
    """Verify if the sector contains the pattern."""
    success, data = read_sector_raw(drive, sector)
    if success and data == pattern * (SECTOR_SIZE // len(pattern)):
        return True
    return False

def repair_sector(settings, drive, sector, patterns, verbose=True):
    max_repair_attempts = settings['repair_sector_attempts']
    max_repair_writes = settings['repair_sector_write']
    max_repair_reads = settings['repair_sector_read']

    for attempt in range(max_repair_attempts):
        for pattern in patterns:
            for _ in range(max_repair_writes):
                write_sector_raw(drive, sector, pattern)

        for _ in range(max_repair_reads):
            if verify_sector(drive, sector, pattern):
                return True, attempt + 1

    if verbose:
        print(f"Sector {sector} could not be repaired after {max_repair_attempts} attempts")
    return False, max_repair_attempts

def f1_mode(settings, drive):
    print(f"Running f1 mode on drive {drive}...")
    pattern_cycle = 0
    patterns = [b'\x55', b'\xAA']  # Binary patterns

    min_sector = settings['min_sector']
    max_sector = settings['max_sector']
    f1_sector_write = settings['f1_sector_write']
    f1_sector_read = settings['f1_sector_read']
    f1_sector_attempts = settings['f1_sector_attempts']

    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    for sector in range(min_sector, max_sector):
        attempts = 0
        while attempts < f1_sector_attempts:
            for pattern in patterns:
                for _ in range(f1_sector_write):
                    write_sector_raw(drive, sector, pattern)

            success = True
            for _ in range(f1_sector_read):
                if not verify_sector(drive, sector, pattern):
                    success = False
                    break

            if success:
                break
            else:
                attempts += 1

        with open(recovered_sectors_file, 'a') as f:
            status = "+" if success else "-"
            f.write(f"{sector} | {status} | {attempts} | {f1_sector_write * 2} | {f1_sector_read} | {f1_sector_attempts} | {'*' if success else '.'}\n")

def recovery_mode(settings, drive):
    print(f"Running recovery mode on drive {drive}...")
    patterns = [b'\x55', b'\xAA']  # Binary patterns

    min_sector = settings['min_sector']
    max_sector = settings['max_sector']
    repair_sector_write = settings['repair_sector_write']
    repair_sector_read = settings['repair_sector_read']
    repair_sector_attempts = settings['repair_sector_attempts']

    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    for sector in range(min_sector, max_sector):
        success, attempts = repair_sector(settings, drive, sector, patterns)
        with open(recovered_sectors_file, 'a') as f:
            status = "+" if success else "-"
            f.write(f"{sector} | {status} | {attempts} | {repair_sector_write * 2} | {repair_sector_read} | {repair_sector_attempts} | {'*' if success else '.'}\n")

def regenerator_mode(settings, drive):
    print(f"Running regenerator mode on drive {drive}...")
    patterns = [b'\x55', b'\xAA']  # Binary patterns

    min_sector = settings['min_sector']
    max_sector = settings['max_sector']
    regenerator_sector_write = settings['regenerator_sector_write']
    regenerator_sector_read = settings['regenerator_sector_read']
    regenerator_sector_attempts = settings['regenerator_sector_attempts']

    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    for sector in range(min_sector, max_sector):
        success, attempts = repair_sector(settings, drive, sector, patterns)
        with open(recovered_sectors_file, 'a') as f:
            status = "+" if success else "-"
            f.write(f"{sector} | {status} | {attempts} | {regenerator_sector_write * 2} | {regenerator_sector_read} | {regenerator_sector_attempts} | {'*' if success else '.'}\n")

def workout_mode(settings, drive):
    if not os.path.exists(recovered_sectors_file):
        print("No recovered sectors file found.")
        return

    test_unstable = input("Do you want to test unstable sectors again? (y/n): ").lower() == 'y'

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
            if status == "+" or (test_unstable and status == "!"):
                repair_sector(settings, drive, sector, 0)

def main():
    settings = read_settings()

    # Initialize the recovered sectors file with a title line
    if not os.path.exists(recovered_sectors_file):
        with open(recovered_sectors_file, 'w') as f:
            f.write("Sector | Status | Attempts | Writes | Reads | Max Attempts | Notes\n")

    print("Select mode:")
    print("1. Repair mode")
    print("2. Workout mode")
    print("3. f1 mode")
    print("4. Regenerator mode")
    choice = input("Enter your choice: ")

    if choice in ['1', '2', '3', '4']:
        drive = select_drive()
        if drive:
            if choice == '1':
                recovery_mode(settings, drive)
            elif choice == '2':
                workout_mode(settings, drive)
            elif choice == '3':
                f1_mode(settings, drive)
            elif choice == '4':
                regenerator_mode(settings, drive)
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()