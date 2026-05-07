#!/usr/bin/env python3
import sys
import json
import struct
import subprocess
import os

def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        sys.exit(0)
    msg_length = struct.unpack('@I', raw_length)[0]
    message = sys.stdin.buffer.read(msg_length).decode('utf-8')
    return json.loads(message)

def send_message(message):
    encoded = json.dumps(message).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('@I', len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()

def process_command(msg):
    action = msg.get("action")
    
    if action == "write_file":
        filepath = msg.get("filepath")
        content = msg.get("content")
        with open(filepath, 'w') as f:
            f.write(content)
        return {"status": "success", "message": f"Wrote to {filepath}"}
        
    elif action == "run_shell":
        command = msg.get("command")
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return {"status": "success", "output": result.stdout, "error": result.stderr}

while True:
    msg = read_message()
    response = process_command(msg)
    send_message(response)
