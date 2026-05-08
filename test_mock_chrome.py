import sys
import json
import struct
import subprocess
import threading

def read_thread(process):
    """Reads standard output from the host process (simulating Chrome receiving data)."""
    while True:
        # Read the first 4 bytes (message length)
        raw_length = process.stdout.read(4)
        if len(raw_length) == 0:
            print("[Mock Chrome] Host process ended.")
            break
        
        # Unpack the message length
        message_length = struct.unpack('@I', raw_length)[0]
        
        # Read the actual message
        message = process.stdout.read(message_length).decode('utf-8')
        print(f"\n[Mock Chrome] Received from Host: {message}")

def send_message(process, message_dict):
    """Sends a formatted native message to the host process."""
    encoded_content = json.dumps(message_dict).encode('utf-8')
    # Chrome prefixes the message with the 4-byte length
    encoded_length = struct.pack('@I', len(encoded_content))
    
    process.stdin.write(encoded_length)
    process.stdin.write(encoded_content)
    process.stdin.flush()
    print(f"[Mock Chrome] Sent: {message_dict}")

if __name__ == '__main__':
    print("Starting Mock Chrome environment...")
    
    # Start the actual host script as a subprocess
    # Note: Make sure host.py is executable or run it via python
    try:
        host_process = subprocess.Popen(
            [sys.executable, 'host.py'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE # Capture stderr just in case
        )
    except Exception as e:
        print(f"Failed to start host.py: {e}")
        sys.exit(1)

    # Start listening to host output in a separate thread
    listener = threading.Thread(target=read_thread, args=(host_process,), daemon=True)
    listener.start()

    # 1. Send a ping or test message
    test_message = {"action": "ping", "data": "Hello from Mock Chrome!"}
    send_message(host_process, test_message)

    # Keep alive for a moment to let responses arrive
    import time
    time.sleep(3)
    host_process.terminate()