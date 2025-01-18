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
        'max_retries': int(config['DEFAULT'].get('max_retries', 3)),
        'max_repair_latency': int(config['DEFAULT'].get('max_repair_latency', 50)),
        'min_sector': int(config['DEFAULT'].get('min_sector', 0)),
        'max_sector': int(config['DEFAULT'].get('max_sector', 0)),
        'regenerator_reads': int(config['DEFAULT'].get('regenerator_reads', 32))
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
        if e.winerror == 32:  # ERROR_SHARING_VIOLATION
            print(f"Error reading sector {sector}: {e}. Retrying...")
            time.sleep(1)  # Wait briefly before retrying
            return read_sector_raw(drive, sector)
        else:
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

def verify_sector(drive, sector, pattern):
    """Verify if the sector contains the pattern."""
    success, data = read_sector_raw(drive, sector)
    if success and data == pattern * (SECTOR_SIZE // len(pattern)):
        return True
    return False

def repair_sector(settings, drive, sector, pattern_cycle, verbose=True):
    max_latency = settings['max_latency']
    max_retries = settings['max_retries']
    max_repair_latency = settings['max_repair_latency']
    patterns = [b'\x55' * SECTOR_SIZE, b'\xAA' * SECTOR_SIZE]  # Binary patterns

    attempt = 0
    while attempt < max_retries:
        if verbose:
            print(f"Reading sector {sector} (Attempt {attempt + 1})...")
        start_time = time.time()
        success, data = read_sector_raw(drive, sector)
        latency = (time.time() - start_time) * 1000  # in milliseconds
        time_spent = time.time() - start_time

        if success and latency <= max_repair_latency:
            if verbose:
                print(f"Sector {sector} read successfully with latency {latency:.2f} ms")
            return True, attempt + 1, latency, time_spent, "R"

        for pattern in patterns:
            if verbose:
                print(f"Writing pattern to sector {sector}...")
            write_sector_raw(drive, sector, pattern)

        if verbose:
            print(f"Reading sector {sector} again after writing patterns...")
        start_time = time.time()
        success, data = read_sector_raw(drive, sector)
        latency = (time.time() - start_time) * 1000  # in milliseconds
        time_spent = time.time() - start_time
        if success and latency <= max_repair_latency:
            if verbose:
                print(f"Sector {sector} repaired successfully after writing patterns with latency {latency:.2f} ms")
            return True, attempt + 1, latency, time_spent, "RW"

        attempt += 1

    if verbose:
        print(f"Sector {sector} could not be repaired after {max_retries} attempts")
    return False, max_retries, latency, time_spent, "-"

def repair_mode(settings, drive, check_mode=False):
    print(f"Repairing sectors on drive {drive}...")
    pattern_cycle = 0

    min_sector = settings['min_sector']
    max_sector = settings['max_sector']

    # Set default sector range (0 to 128 MB) if max_sector is 0
    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    for sector in range(min_sector, max_sector):
        is_good, attempts, latency, time_spent, error_type = repair_sector(settings, drive, sector, pattern_cycle)
        pattern_cycle += 1
        with open(recovered_sectors_file, 'a') as f:
            status = "+" if is_good else "-"
            f.write(f"{sector} | {status} | {attempts} | 8 | {latency if is_good else '-'} | {time_spent} | {error_type} | {'*' if is_good else '.'}\n")

def f1_mode(settings, drive):
    print(f"Checking and repairing sectors on drive {drive}...")
    pattern_cycle = 0

    min_sector = settings['min_sector']
    max_sector = settings['max_sector']

    # Set default sector range (0 to 128 MB) if max_sector is 0
    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    patterns = [b'\x55' * SECTOR_SIZE, b'\xAA' * SECTOR_SIZE]  # Binary patterns

    for sector in range(min_sector, max_sector):
        print(f"Checking sector {sector}...")
        success, data = read_sector_raw(drive, sector)
        if not success:
            print(f"Sector {sector} read failed. Attempting repair...")
            is_good, attempts, latency, time_spent, error_type = repair_sector(settings, drive, sector, pattern_cycle)
        else:
            pattern = patterns[pattern_cycle % 2]
            if data == pattern:
                print(f"Sector {sector} verified successfully. Skipping...")
                continue
            else:
                print(f"Sector {sector} verification failed. Attempting repair...")
                is_good, attempts, latency, time_spent, error_type = repair_sector(settings, drive, sector, pattern_cycle)
        pattern_cycle += 1
        with open(recovered_sectors_file, 'a') as f:
            status = "+" if is_good else "-"
            f.write(f"{sector} | {status} | {attempts} | 8 | {latency if is_good else '-'} | {time_spent} | {error_type} | {'*' if is_good else '.'}\n")

def regenerator_mode(settings, drive):
    print(f"Regenerating sectors on drive {drive}...")
    pattern_cycle = 0
    regenerator_reads = settings['regenerator_reads']

    min_sector = settings['min_sector']
    max_sector = settings['max_sector']

    # Set default sector range (0 to 128 MB) if max_sector is 0
    if max_sector == 0:
        max_sector = (128 * 1024 * 1024) // SECTOR_SIZE

    for sector in range(min_sector, max_sector):
        read_attempt = 0
        current_fail_count = 0
        while read_attempt < regenerator_reads:
            print(f"Reading sector {sector} (Read attempt {read_attempt + 1}/{regenerator_reads})...")
            start_time = time.time()
            success, data = read_sector_raw(drive, sector)
            latency = (time.time() - start_time) * 1000  # in milliseconds
            if success and latency <= settings['max_repair_latency']:
                print(f"Sector {sector} read successfully with latency {latency:.2f} ms")
                read_attempt += 1
            else:
                print(f"Sector {sector} read failed or has high latency. Attempting repair...")
                is_good, attempts, latency, time_spent, error_type = repair_sector(settings, drive, sector, pattern_cycle)
                with open(recovered_sectors_file, 'a') as f:
                    status = "+" if is_good else "-"
                    f.write(f"{sector} | {status} | {attempts} | 8 | {latency if is_good else '-'} | {time_spent} | {error_type} | {'*' if is_good else '.'}\n")
                # Move to the next sector, then come back to the current sector
                if sector + 1 < max_sector:
                    next_sector = sector + 1
                    print(f"Reading next sector {next_sector} to avoid caching issues.")
                    _, _ = read_sector_raw(drive, next_sector)
                time.sleep(0.1)  # Slight delay to avoid caching

                if current_fail_count < settings['max_retries']:
                    read_attempt = 0
                    current_fail_count += 1
                else:
                    print(f"Sector {sector} failed to be repaired after {settings['max_retries']} retries. Skipping sector.")
                    with open(recovered_sectors_file, 'a') as f:
                        f.write(f"{sector} | - | {settings['max_retries']} | 8 | - | - | F | *\n")
                    break
        pattern_cycle += 1

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
                repair_mode(settings, drive)
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