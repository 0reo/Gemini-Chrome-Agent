#!/usr/bin/env python3
import sys
import json
import struct
import subprocess
import os

# Set binary mode for standard streams to handle Native Messaging protocol
def get_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        sys.exit(0)
    message_length = struct.unpack('@I', raw_length)[0]
    message = sys.stdin.buffer.read(message_length).decode('utf-8')
    return json.loads(message)

def send_message(message_dict):
    encoded = json.dumps(message_dict).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('@I', len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()

while True:
    try:
        msg = get_message()
        action = msg.get('action')
        
        if action == 'run_shell':
            command = msg.get('command')
            try:
                # Capture both stdout and stderr
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
                output = result.stdout
                if result.stderr:
                    output += "\n--- Error Output ---\n" + result.stderr
                
                # If command produced absolutely no text, give a helpful placeholder
                if not output.strip():
                    output = "[Command executed successfully with no output]"
                    
                send_message({'status': 'success', 'output': output})
            except Exception as e:
                send_message({'status': 'error', 'error': f'Subprocess Exception: {str(e)}'})
                
        elif action == 'write_file':
            filepath = msg.get('filepath')
            content = msg.get('content')
            try:
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, 'w') as f:
                    f.write(content)
                send_message({'status': 'success', 'message': f'File {filepath} written.'})
            except Exception as e:
                send_message({'status': 'error', 'error': f'File write error: {str(e)}'})
        else:
            send_message({'status': 'error', 'error': 'Unknown action'})
            
    except Exception as fatal_error:
        # Avoid crashing the host if possible; send the error back
        try:
            send_message({'status': 'fatal_error', 'error': str(fatal_error)})
        except:
            sys.exit(1)