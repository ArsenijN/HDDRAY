import os
import time
import configparser
import subprocess
from ctypes import windll, WinError, create_string_buffer, c_ulonglong, byref

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
        'regenerator_sector_write': int(config['DEFAULT'].get('regenerator_sector_write', 8)),
        'regenerator_sector_read': int(config['DEFAULT'].get('regenerator_sector_read', 1)),
        'regenerator_sector_attempts': int(config['DEFAULT'].get('regenerator_sector_attempts', 4)),
        'f1_sector_write': int(config['DEFAULT'].get('f1_sector_write', 3)),
        'f1_sector_read': int(config['DEFAULT'].get('f1_sector_read', 5)),
        'f1_sector_attempts': int(config['DEFAULT'].get('f1_sector_attempts', 3)),
        'repair_sector_write': int(config['DEFAULT'].get('repair_sector_write', 3)),
        'repair_sector_read': int(config['DEFAULT'].get('repair_sector_read', 5)),
        'repair_sector_attempts': int(config['DEFAULT'].get('repair_sector_attempts', 3)),
        'mode': int(config['DEFAULT'].get('mode', 1)),
        'drive_number': int(config['DEFAULT'].get('drive_number', 1)),
        'auto_mode': int(config['DEFAULT'].get('auto_mode', 1)),
        'error_use_handle': int(config['DEFAULT'].get('error_use_handle', 3))  # New setting for retry attempts
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

def select_drive(settings):
    """Automatically or manually select a drive based on the settings."""
    drives = list_raw_drives()
    if not drives:
        print("No drives found.")
        return None

    if settings['auto_mode']:
        drive_index = settings['drive_number'] - 1  # Convert to 0-based index
        if 0 <= drive_index < len(drives):
            device_id, model, size = drives[drive_index]
            print(f"Attention: Using drive {drive_index + 1} ({model}, {size}GB) [{device_id}]")
            time.sleep(5)  # Wait for 5 seconds
            return device_id
        print("Invalid drive number in settings.")
        return None
    else:
        print("What drive to use:")
        for i, (device_id, model, size) in enumerate(drives, start=1):
            print(f"{i}. {model} ({size}GB) [{device_id}]")
        choice = int(input("Enter the drive number: ")) - 1
        if 0 <= choice < len(drives):
            return drives[choice][0]
        print("Invalid choice.")
        return None

def open_drive(drive, access_mode):
    """Open a drive with the specified access mode and exclusive access."""
    try:
        handle = windll.kernel32.CreateFileW(
            drive,  # Raw drive path
            access_mode,  # Access mode
            0,  # No sharing (exclusive access)
            None,
            3,  # OPEN_EXISTING
            0,
            None,
        )
        if handle == -1:
            raise WinError()
        return handle
    except WinError as e:
        print(f"Error opening drive {drive}: {e}")
        return None

def close_drive(handle):
    """Close the drive handle."""
    if handle:
        windll.kernel32.CloseHandle(handle)

def read_sector_raw(drive, sector, retries):
    """Read a raw sector with retry mechanism."""
    for attempt in range(retries):
        handle = open_drive(drive, 0x80000000)  # GENERIC_READ
        if not handle:
            if attempt < retries - 1:
                time.sleep(1)  # Wait a bit before retrying
                continue
            else:
                return False, None, None

        try:
            buffer = create_string_buffer(SECTOR_SIZE)
            distance_to_move = c_ulonglong(sector * SECTOR_SIZE)
            if not windll.kernel32.SetFilePointerEx(handle, distance_to_move, None, 0):
                raise WinError()

            bytes_read = c_ulonglong(0)
            start_time = time.time()  # Start timing the read operation
            if not windll.kernel32.ReadFile(handle, buffer, SECTOR_SIZE, byref(bytes_read), None):
                raise WinError()
            end_time = time.time()  # End timing the read operation
            latency = (end_time - start_time) * 1000  # Convert to milliseconds

            close_drive(handle)
            return True, buffer.raw, latency
        except PermissionError as e:
            print(f"Error reading sector {sector}: {e}")
            close_drive(handle)
            if attempt < retries - 1:
                time.sleep(1)  # Wait a bit before retrying
            else:
                return False, None, None
        except WinError as e:
            print(f"Error reading sector {sector}: {e}")
            close_drive(handle)
            return False, None, None

def write_sector_raw(drive, sector, pattern, retries):
    """Write a raw sector with retry mechanism."""
    for attempt in range(retries):
        handle = open_drive(drive, 0xC0000000)  # GENERIC_READ | GENERIC_WRITE
        if not handle:
            if attempt < retries - 1:
                time.sleep(1)  # Wait a bit before retrying
                continue
            else:
                return False

        try:
            buffer = create_string_buffer(pattern * (SECTOR_SIZE // len(pattern)))
            distance_to_move = c_ulonglong(sector * SECTOR_SIZE)
            if not windll.kernel32.SetFilePointerEx(handle, distance_to_move, None, 0):
                raise WinError()

            bytes_written = c_ulonglong(0)
            if not windll.kernel32.WriteFile(handle, buffer, SECTOR_SIZE, byref(bytes_written), None):
                raise WinError()

            close_drive(handle)
            return True
        except Exception as e:
            print(f"Error writing sector {sector}: {e}")
            close_drive(handle)
            if attempt < retries - 1:
                time.sleep(1)  # Wait a bit before retrying
            else:
                return False

def verify_sector(drive, sector, pattern, retries):
    """Verify if the sector contains the pattern."""
    success, data, latency = read_sector_raw(drive, sector, retries)
    if success and data == pattern * (SECTOR_SIZE // len(pattern)):
        return True, latency
    return False, latency

def repair_sector(settings, drive, sector, patterns, verbose=True):
    max_repair_attempts = settings['repair_sector_attempts']
    max_repair_writes = settings['repair_sector_write']
    max_repair_reads = settings['repair_sector_read']
    max_latency = settings['max_latency']
    retries = settings['error_use_handle']

    for attempt in range(max_repair_attempts):
        for pattern in patterns:
            for _ in range(max_repair_writes):
                write_sector_raw(drive, sector, pattern, retries)

        for _ in range(max_repair_reads):
            success, latency = verify_sector(drive, sector, pattern, retries)
            if success and latency <= max_latency:
                return True, attempt + 1
            elif latency > max_latency:
                print(f"Sector {sector} access time {latency:.2f}ms exceeds max latency {max_latency}ms")
                return False, attempt + 1

    if verbose:
        print(f"Sector {sector} could not be repaired after {max_repair_attempts} attempts")
    return False, max_repair_attempts

def f1_mode(settings, drive):
    print(f"Running f1 mode on drive {drive}...")
    patterns = [b'\x55', b'\xAA']  # Binary patterns

    min_sector = settings['min_sector']
    max_sector = settings['max_sector']
    f1_sector_write = settings['f1_sector_write']
    f1_sector_read = settings['f1_sector_read']
    f1_sector_attempts = settings['f1_sector_attempts']
    max_latency = settings['max_latency']
    retries = settings['error_use_handle']

    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    for sector in range(min_sector, max_sector):
        print(f"Processing sector {sector}...")
        attempts = 0
        while attempts < f1_sector_attempts:
            for pattern in patterns:
                for _ in range(f1_sector_write):
                    write_sector_raw(drive, sector, pattern, retries)

            success = True
            for _ in range(f1_sector_read):
                verified, latency = verify_sector(drive, sector, pattern, retries)
                if not verified or latency > max_latency:
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
    max_latency = settings['max_latency']
    retries = settings['error_use_handle']

    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    for sector in range(min_sector, max_sector):
        print(f"Processing sector {sector}...")
        # First attempt to read the sector
        success, data, latency = read_sector_raw(drive, sector, retries)
        if success and latency <= max_latency:
            # Sector read successfully within allowed latency, no repair needed
            status = "+"
            attempts = 0
        else:
            if latency is not None and latency > max_latency:
                print(f"Sector {sector} access time {latency:.2f}ms exceeds max latency {max_latency}ms")
            # Sector read failed or exceeded max latency, perform repair attempts
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
    max_latency = settings['max_latency']
    retries = settings['error_use_handle']

    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    for sector in range(min_sector, max_sector):
        print(f"Processing sector {sector}...")
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
            parts = line.split("|")
            if len(parts) < 7 or not parts[0].strip().isdigit():
                continue  # Skip header or invalid lines

            sector = int(parts[0].strip())
            status = parts[1].strip()
            if status == "-" or (test_unstable and status == "!"):
                repair_sector(settings, drive, sector, [b'\x55', b'\xAA'])

def main():
    settings = read_settings()

    # Initialize the recovered sectors file with a title line
    if not os.path.exists(recovered_sectors_file):
        with open(recovered_sectors_file, 'w') as f:
            f.write("Sector | Status | Attempts | Writes | Reads | Max Attempts | Notes\n")

    drive = select_drive(settings)
    if not drive:
        print("Failed to select drive.")
        return

    if settings['auto_mode']:
        mode = settings['mode']
        if mode == 1:
            recovery_mode(settings, drive)
        elif mode == 2:
            workout_mode(settings, drive)
        elif mode == 3:
            f1_mode(settings, drive)
        elif mode == 4:
            regenerator_mode(settings, drive)
        else:
            print("Invalid mode in settings.")
    else:
        print("Select mode:")
        print("1. Recovery mode")
        print("2. Workout mode")
        print("3. f1 mode")
        print("4. Regenerator mode")
        choice = input("Enter your choice: ")
        if choice in ['1', '2', '3', '4']:
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
