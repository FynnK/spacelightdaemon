import os
import asyncio
import spacenav
from wled import WLED
import daemon
import sys
import argparse
import signal
import datetime

color_temp = 0
brightness = 0
on = False
is_running = True

# Get the directory of the script
script_directory = os.path.dirname(os.path.abspath(__file__))
# Define the PID file path
PID_FILE = os.path.join(script_directory, ".spacelightd.pid")
# Define the log file path
LOG_FILE = os.path.join(script_directory, "daemon.log")

# Function to log messages with timestamps
def log_message(message):
    with open(LOG_FILE, 'a') as f:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {message}\n")


async def handle_spacenav_events():
    global color_temp, brightness, on, is_running

    while is_running:
        try:
            spacenav.open()
            log_message("Connection to SpaceNav driver established.")
            break
        except spacenav.ConnectionError:
            log_message("No connection to the SpaceNav driver. Retrying...")
            await asyncio.sleep(1)

    while is_running:
        event = spacenav.poll()
        if isinstance(event, spacenav.MotionEvent) and on:
            new_color_temp = max(0, min(255, color_temp - event.rz / 300.0))
            new_brightness = max(1, min(255, brightness - event.rx / 300.0))  # Inverted direction

            if new_color_temp != color_temp or new_brightness != brightness:
                color_temp = new_color_temp
                brightness = new_brightness
                if verbose:
                    log_message(f"Color temperature: {color_temp}, Brightness: {brightness}")

        elif isinstance(event, spacenav.ButtonEvent):
            if event.button == 0 and event.pressed == 1:
                on = not on
                if verbose:
                    log_message(f"Switched {'on' if on else 'off'}")
            if event.button == 1 and event.pressed == 1:
                color_temp = 127
                brightness = 255
                on = True
                if verbose:
                    log_message(f"Set color temperature: {color_temp}, Brightness: {brightness}, Switched on")

        await asyncio.sleep(0.01)

async def set_led_settings(ip_address):
    global color_temp, brightness, on, is_running

    last_color_temp = None
    last_brightness = None
    last_on = None

    led = None
    while is_running:
        try:
            if led is None or not led.connected:
                led = WLED(ip_address)
                await asyncio.wait_for(led.connect(), timeout=5)
                if led.connected:
                    if verbose:
                        log_message("Connected to WLED!")
                    await asyncio.sleep(0.5)  # Sleep to allow time for stable connection

            while is_running:
                # Check if LED settings need to be updated
                if color_temp != last_color_temp or brightness != last_brightness or on != last_on:
                    await led.master(on=on, brightness=255)
                    await led.segment(0, brightness=int(brightness), cct=int(color_temp))

                    # Update last set values
                    last_color_temp = color_temp
                    last_brightness = brightness
                    last_on = on

                await asyncio.sleep(0.01)
        except asyncio.TimeoutError:
            log_message("Connection to WLED timed out. Retrying...")
        except Exception as e:
            log_message(f"An error occurred while connecting to WLED: {e}")
        finally:
            if led is not None:
                await led.close()
                led = None

        await asyncio.sleep(1)


async def main(logfile, ip_address, verbose=False):
    log_message("Daemon started")
    await asyncio.gather(handle_spacenav_events(), set_led_settings(ip_address))
    log_message("Daemon stopped")

def start_daemon(logfile, ip_address, verbose=False):
    with daemon.DaemonContext(stdout=sys.stdout, stderr=sys.stderr):
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        with open(LOG_FILE, 'w') as log:
            sys.stdout = log
            sys.stderr = log
            asyncio.run(main(logfile, ip_address, verbose))

def stop_daemon():
    if os.path.exists(PID_FILE):
        with open(PID_FILE, 'r') as f:
            pid = int(f.read())
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                print("PID file exists but no process running. Removing stale PID file.")
            else:
                print("Daemon stopped successfully.")
            finally:
                os.remove(PID_FILE)
    else:
        print("PID file does not exist. Daemon may not be running.")

def signal_handler(sig, frame):
    stop_daemon()
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daemon for controlling LED lights with SpaceNav")
    parser.add_argument("-l", "--log", metavar="LOG_FILE", default="~/daemon.log", help="Specify the log file location")
    parser.add_argument("-ip", "--ip_address", metavar="IP_ADDRESS", default="cctwled.local", help="Specify the IP address or hostname of the WLED device")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("action", choices=["start", "stop"], help="Specify the action to perform (start or stop)")
    args = parser.parse_args()

    logfile = os.path.expanduser(args.log)
    ip_address = args.ip_address
    verbose = args.verbose

    if args.action == "start":
        signal.signal(signal.SIGINT, signal_handler)
        start_daemon(logfile, ip_address, verbose)
    elif args.action == "stop":
        stop_daemon()
