import os
import time
import configparser
import random
import subprocess
from ctypes import windll

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
        # Run PowerShell command to get drives
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

# Select drive
def select_drive():
    drives = list_drives()
    if not drives:
        print("No drives found.")
        return None

    print("What drive to use:")
    for i, (device_id, model, size) in enumerate(drives, start=1):
        print(f"{i}. {model} ({size}GB) [{device_id}]")

    choice = int(input("Enter the drive number: ")) - 1
    if 0 <= choice < len(drives):
        return drives[choice][0]  # Return the selected device ID
    print("Invalid choice.")
    return None

# Get drive range (min and max sectors)
def get_drive_range(drive):
    print(f"Getting range for drive: {drive}")
    # Placeholder for actual range detection, set arbitrary range
    min_sector = 0
    max_sector = 1000000  # Example value, replace with accurate detection
    return min_sector, max_sector

# Write to a sector with alternating patterns
def write_sector(sector, cycle):
    pattern = "01010101" if cycle % 2 == 0 else "10101010"
    print(f"Writing pattern {pattern} to sector {sector}")
    # Simulate sector writing with dummy access time
    return random.randint(50, 500)

# Repair mode
def repair_mode(settings, drive):
    min_sector, max_sector = get_drive_range(drive)
    print(f"Repairing sectors from {min_sector} to {max_sector} on drive {drive}...")
    with open('list_of_recovered_sectors.txt', 'a') as logfile:
        for sector in range(min_sector, max_sector + 1):
            try_count = 0
            cycle = 0
            while try_count < settings['max_try_count']:
                access_time = write_sector(sector, cycle)
                cycle += 1
                if access_time <= settings['access_time_threshold']:
                    print(f"Sector {sector} repaired successfully.")
                    logfile.write(f"{sector} | + | {try_count} | {settings['max_try_count']} | {access_time}\n")
                    break
                try_count += 1
                print(f"Retrying sector {sector}, try {try_count}...")
            else:
                print(f"Sector {sector} is unrecoverable.")
                logfile.write(f"{sector} | _ | {settings['max_try_count']} | {settings['max_try_count']} | -\n")

# Main menu
def main():
    initialize_settings()
    settings = read_settings()

    print("Select mode:")
    print("1. Repair mode")
    choice = input("Enter your choice: ")

    if choice == '1':
        drive = select_drive()
        if drive:
            repair_mode(settings, drive)
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()
