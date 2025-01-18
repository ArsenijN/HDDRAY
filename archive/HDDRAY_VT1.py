import os
import time
import configparser
import random

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

# Simulate sector access time (for testing purposes)
def simulate_access_time(sector, write=False):
    if write:
        return random.randint(50, 500)  # Simulate varying write times
    return random.randint(10, 100)  # Simulate varying read times

# Calibrate access time
def calibrate_access_time():
    print("Calibrating access time...")
    times = []
    for _ in range(5):
        access_time = simulate_access_time(0)
        print(f"Access time: {access_time} ms")
        times.append(access_time)
        time.sleep(0.1)
    avg_time = sum(times) / len(times)
    print(f"Calibrated average access time: {avg_time:.2f} ms")
    return avg_time

# Write to a sector and measure access time
def write_sector(sector):
    return simulate_access_time(sector, write=True)

# Read from a sector and check for errors
def read_sector(sector):
    access_time = simulate_access_time(sector)
    if random.random() > 0.9:  # Simulate 10% chance of read failure
        print(f"Read error at sector {sector}")
        return False, access_time
    return True, access_time

# Repair mode
def repair_mode(settings, drive_range):
    min_sector, max_sector = drive_range
    print(f"Repairing sectors from {min_sector} to {max_sector}...")
    with open('list_of_recovered_sectors.txt', 'a') as logfile:
        for sector in range(min_sector, max_sector + 1):
            try_count = 0
            while try_count < settings['max_try_count']:
                access_time = write_sector(sector)
                if access_time <= settings['access_time_threshold']:
                    success, _ = read_sector(sector)
                    if success:
                        logfile.write(f"{sector} | + | {try_count} | {settings['max_try_count']} | {access_time} | * | -\n")
                        print(f"Sector {sector} repaired successfully.")
                        break
                try_count += 1
                print(f"Retrying sector {sector}, try {try_count}...")
            else:
                logfile.write(f"{sector} | _ | {settings['max_try_count']} | {settings['max_try_count']} | - | . | RW\n")
                print(f"Sector {sector} is unrecoverable.")

# Workout mode
def workout_mode(settings):
    print("Starting workout mode...")
    if not os.path.exists('list_of_recovered_sectors.txt'):
        print("No recovered sectors to workout.")
        return

    with open('list_of_recovered_sectors.txt', 'r') as logfile:
        sectors = logfile.readlines()

    for line in sectors:
        sector, status, *_ = line.strip().split('|')
        sector = int(sector.strip())
        if status.strip() == '_':
            print(f"Testing bad sector {sector}...")
            success, _ = read_sector(sector)
            if success:
                write_sector(sector)
                print(f"Sector {sector} recovered during workout.")

# Main menu
def main():
    initialize_settings()
    settings = read_settings()

    print("Select mode:")
    print("1. Repair mode")
    print("2. Workout mode")
    choice = input("Enter your choice: ")

    if choice == '1':
        drive_range = input("Enter sector range (min max): ")
        if not drive_range.strip():
            print("Using full drive range...")
            drive_range = (0, 1000000)  # Placeholder for full drive range
        else:
            drive_range = tuple(map(int, drive_range.split()))
        repair_mode(settings, drive_range)
    elif choice == '2':
        workout_mode(settings)
    else:
        print("Invalid choice.")

if __name__ == "__main__":
    main()
